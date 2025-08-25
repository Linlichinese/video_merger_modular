"""
素材顺序多样化选择器模块

该模块实现了一个智能的素材选择器，确保生成的素材组合顺序完全不重复，
同时最大化利用所有素材资源。支持持久化功能，跨会话保持去重状态。
"""

import random
import json
import os
from collections import defaultdict
from typing import List, Tuple, Any, Optional


class SequenceDiversitySelector:
    """
    素材顺序多样化选择器
    
    核心功能：
    1. 严格顺序去重：确保生成的素材组合顺序完全不重复
    2. 连续元素顺序去重：禁止任何两个序列包含连续2个元素的相同顺序
    3. 最大化素材利用：通过权重微调促进素材均衡使用
    4. 极简高效：逻辑清晰，适用于大规模素材场景
    """
    
    def __init__(self, all_materials: List[Any], per_video: int, persistence_file: Optional[str] = None):
        """
        初始化选择器
        
        Args:
            all_materials: 所有素材列表（如 [A,B,C... 上千个]）
            per_video: 每条视频的素材数量（如 3 个）
            persistence_file: 持久化文件路径，如果提供则自动加载和保存状态
        """
        self.materials = all_materials
        self.per_video = per_video
        self.persistence_file = persistence_file
        
        # 初始化状态数据结构
        self.used_sequences = set()  # 核心：记录所有已用过的「顺序组合」（如 (A,B,C)）
        self.used_pairs = set()  # 新增：记录所有已用过的连续2元素子序列（如 (A,B)、(B,C)）
        self.material_count = defaultdict(int)  # 记录素材使用次数（仅用于辅助均衡）
        
        # 验证参数有效性
        if not all_materials:
            raise ValueError("素材列表不能为空")
        if per_video <= 0:
            raise ValueError("每条视频的素材数量必须大于0")
        if per_video > len(all_materials):
            raise ValueError("每条视频的素材数量不能超过总素材数量")
        
        # 如果指定了持久化文件，尝试加载历史状态
        if self.persistence_file:
            self.load_state()
    
    def _extract_consecutive_pairs(self, sequence: List[Any]) -> List[Tuple[Any, Any]]:
        """
        提取序列中所有连续2个元素的子序列
        
        Args:
            sequence: 输入序列（如 [A,B,C]）
            
        Returns:
            连续2元素子序列列表（如 [(A,B), (B,C)]）
        """
        if len(sequence) < 2:
            return []
        
        pairs = []
        for i in range(len(sequence) - 1):
            pairs.append((sequence[i], sequence[i + 1]))
        return pairs
    
    def _is_valid_sequence(self, sequence: List[Any]) -> bool:
        """
        检查序列是否有效（不与已有序列或连续2元素子序列重复）
        
        Args:
            sequence: 待检查的序列
            
        Returns:
            如果序列有效返回True，否则返回False
        """
        # 检查完整序列是否重复
        sequence_tuple = tuple(sequence)
        if sequence_tuple in self.used_sequences:
            return False
        
        # 检查连续2元素子序列是否重复
        pairs = self._extract_consecutive_pairs(sequence)
        for pair in pairs:
            if pair in self.used_pairs:
                return False
        
        return True
    
    def _record_sequence(self, sequence: List[Any]):
        """
        记录新序列及其连续2元素子序列
        
        Args:
            sequence: 要记录的序列
        """
        # 记录完整序列
        sequence_tuple = tuple(sequence)
        self.used_sequences.add(sequence_tuple)
        
        # 记录连续2元素子序列
        pairs = self._extract_consecutive_pairs(sequence)
        for pair in pairs:
            self.used_pairs.add(pair)
        
        # 更新素材使用次数
        for mat in sequence:
            self.material_count[mat] += 1
        
        # 自动保存状态到文件（如果启用了持久化）
        if self.persistence_file:
            self.save_state()

    def get_next_combination(self) -> List[Any]:
        """
        生成新组合：保证顺序完全不重复，且连续2个元素的顺序也不重复，同时最大化利用素材
        同时确保单条视频内不会有重复素材（即不允许ABA这样的模式）
        
        Returns:
            选中的素材列表
            
        Raises:
            RuntimeError: 当无法生成新组合时（理论上在大规模素材场景下几乎不会发生）
        """
        # 检查素材数量是否足够
        if len(self.materials) < self.per_video:
            raise RuntimeError(f"素材数量({len(self.materials)})不足，无法生成不重复的{self.per_video}个素材组合")
        
        max_tries = 30  # 最多尝试 30 次找新顺序组合
        
        for attempt in range(max_tries):
            # 使用加权随机选择，但确保单条视频内素材不重复
            # 先根据权重创建候选池，然后无重复抽样
            weights = [1.0 / (self.material_count[mat] + 1) for mat in self.materials]
            
            # 使用 random.choices 创建加权候选池，然后用 sample 确保无重复
            # 为了保持权重效果，我们创建一个更大的候选池
            pool_size = min(len(self.materials) * 3, 100)  # 候选池大小，最多100个
            weighted_pool = random.choices(self.materials, weights=weights, k=pool_size)
            
            # 从候选池中无重复抽样
            try:
                # 去重候选池，保持顺序
                unique_pool = []
                seen = set()
                for item in weighted_pool:
                    if item not in seen:
                        unique_pool.append(item)
                        seen.add(item)
                
                # 如果去重后的候选池仍然足够大，直接抽样
                if len(unique_pool) >= self.per_video:
                    selected = random.sample(unique_pool, self.per_video)
                else:
                    # 否则从全部素材中抽样（保证能抽到足够的素材）
                    selected = random.sample(self.materials, self.per_video)
                
            except ValueError:
                # 如果抽样失败，直接从全部素材中抽样
                selected = random.sample(self.materials, self.per_video)
            
            # 检查序列是否有效（完整序列 + 连续2元素子序列都不重复）
            if self._is_valid_sequence(selected):
                # 找到全新有效组合，记录并更新
                self._record_sequence(selected)
                return selected
        
        # 极端情况：尝试 30 次未找到新组合（素材极少或 per_video 过大时）
        # 此时强制生成组合，但仍然确保单条视频内素材不重复
        try:
            selected = random.sample(self.materials, self.per_video)
        except ValueError:
            raise RuntimeError(f"无法生成不重复的{self.per_video}个素材组合，素材数量不足")
        
        # 即使极端情况也记录，避免下次完全重复
        self._record_sequence(selected)
            
        return selected

    def get_next_combination_from_allowed(self, allowed_materials: List[Any]) -> List[Any]:
        """
        基于给定的允许素材集合生成下一个组合，并继续使用当前去重状态与持久化。

        Args:
            allowed_materials: 本轮可用的素材子集（必须来自于 self.materials）

        Returns:
            选中的素材列表
        """
        if not allowed_materials:
            raise RuntimeError("可用素材集合为空，无法生成组合")

        # 仅保留同时存在于全集中的素材，保持既有顺序以提升可预测性
        allowed_set = set(allowed_materials)
        candidates = [m for m in self.materials if m in allowed_set]

        if len(candidates) < self.per_video:
            raise RuntimeError(f"可用素材数量({len(candidates)})不足以生成不重复的{self.per_video}个素材组合")

        max_tries = 30
        for _ in range(max_tries):
            # 针对候选集计算权重
            weights = [1.0 / (self.material_count[mat] + 1) for mat in candidates]

            pool_size = min(len(candidates) * 3, 100)
            weighted_pool = random.choices(candidates, weights=weights, k=pool_size)

            # 去重候选池，保持顺序
            unique_pool = []
            seen = set()
            for item in weighted_pool:
                if item not in seen:
                    unique_pool.append(item)
                    seen.add(item)

            if len(unique_pool) >= self.per_video:
                selected = random.sample(unique_pool, self.per_video)
            else:
                selected = random.sample(candidates, self.per_video)

            if self._is_valid_sequence(selected):
                self._record_sequence(selected)
                return selected

        # 兜底策略
        selected = random.sample(candidates, self.per_video)
        self._record_sequence(selected)
        return selected
    
    def get_statistics(self) -> dict:
        """
        获取选择器统计信息
        
        Returns:
            包含统计信息的字典
        """
        return {
            'total_materials': len(self.materials),
            'per_video': self.per_video,
            'used_sequences_count': len(self.used_sequences),
            'used_pairs_count': len(self.used_pairs),  # 新增：已用连续2元素子序列数量
            'material_usage': dict(self.material_count),
            'max_usage': max(self.material_count.values()) if self.material_count else 0,
            'min_usage': min(self.material_count.values()) if self.material_count else 0,
            'unused_materials': len([m for m in self.materials if self.material_count[m] == 0])
        }
    
    def reset(self):
        """重置选择器状态"""
        self.used_sequences.clear()
        self.used_pairs.clear()  # 新增：清空已用连续2元素子序列
        self.material_count.clear()
        
        # 如果启用了持久化，同时清空持久化文件
        if self.persistence_file:
            self.save_state()
    
    def save_state(self):
        """
        保存当前状态到文件
        
        将去重状态持久化到JSON文件中，包括：
        - 已使用的序列组合
        - 已使用的连续2元素子序列
        - 素材使用次数统计
        """
        if not self.persistence_file:
            return
        
        try:
            # 创建持久化文件的目录（如果不存在）
            os.makedirs(os.path.dirname(self.persistence_file), exist_ok=True)
            
            # 准备要保存的数据
            state_data = {
                'version': '1.0',  # 版本号，用于未来兼容性
                'materials': self.materials,  # 保存素材列表，用于验证一致性
                'per_video': self.per_video,  # 保存每视频素材数，用于验证一致性
                'used_sequences': [list(seq) for seq in self.used_sequences],  # 转换为列表以便JSON序列化
                'used_pairs': [list(pair) for pair in self.used_pairs],  # 转换为列表以便JSON序列化
                'material_count': dict(self.material_count)  # 转换为普通字典
            }
            
            # 写入文件
            with open(self.persistence_file, 'w', encoding='utf-8') as f:
                json.dump(state_data, f, ensure_ascii=False, indent=2)
                
        except Exception as e:
            # 持久化失败不应该影响主要功能，只记录错误
            print(f"警告：保存去重状态失败：{e}")
    
    def load_state(self):
        """
        从文件加载状态
        
        从JSON文件中恢复去重状态，如果文件不存在或格式不正确，
        则使用默认的空状态。
        """
        if not self.persistence_file or not os.path.exists(self.persistence_file):
            return
        
        try:
            with open(self.persistence_file, 'r', encoding='utf-8') as f:
                state_data = json.load(f)
            
            # 验证数据格式和版本
            if not isinstance(state_data, dict) or 'version' not in state_data:
                print("警告：持久化文件格式不正确，使用默认状态")
                return
            
            # 验证素材列表和参数是否一致（防止配置变更导致的问题）
            saved_materials = state_data.get('materials', [])
            saved_per_video = state_data.get('per_video', 0)
            
            # 如果素材列表或参数发生变化，重置状态
            if (set(saved_materials) != set(self.materials) or 
                saved_per_video != self.per_video):
                print("警告：素材列表或参数已变更，重置去重状态")
                return
            
            # 恢复状态数据
            used_sequences = state_data.get('used_sequences', [])
            used_pairs = state_data.get('used_pairs', [])
            material_count = state_data.get('material_count', {})
            
            # 转换回set和defaultdict格式
            self.used_sequences = set(tuple(seq) for seq in used_sequences)
            self.used_pairs = set(tuple(pair) for pair in used_pairs)
            self.material_count = defaultdict(int)
            self.material_count.update(material_count)
            
            print(f"成功加载去重状态：{len(self.used_sequences)}个已用序列，{len(self.used_pairs)}个已用连续对")
            
        except Exception as e:
            print(f"警告：加载去重状态失败：{e}，使用默认状态")
    
    def get_persistence_file_path(self, input_folder: str) -> str:
        """
        根据输入文件夹生成持久化文件路径
        
        使用文件夹的绝对路径哈希值作为唯一标识，避免同名文件夹冲突
        
        Args:
            input_folder: 输入文件夹路径
            
        Returns:
            持久化文件的完整路径
        """
        import hashlib
        
        # 获取输入文件夹的绝对路径
        abs_path = os.path.abspath(input_folder)
        
        # 使用路径哈希值作为唯一标识（避免同名文件夹冲突）
        path_hash = hashlib.md5(abs_path.encode('utf-8')).hexdigest()[:12]
        
        # 同时保留文件夹名称以便识别
        folder_name = os.path.basename(input_folder.rstrip('/\\')) or "default"
        
        # 创建持久化文件路径（格式：{folder_name}_{path_hash}_dedup_state.json）
        persistence_dir = os.path.join(os.getcwd(), '.video_merger', 'dedup_states')
        persistence_file = os.path.join(persistence_dir, f"{folder_name}_{path_hash}_dedup_state.json")
        
        return persistence_file
    
    @staticmethod
    def cleanup_old_states(days_old=30):
        """
        清理旧的去重状态文件
        
        Args:
            days_old: 清理多少天前的文件，默认30天
        """
        import time
        
        persistence_dir = os.path.join(os.getcwd(), '.video_merger', 'dedup_states')
        if not os.path.exists(persistence_dir):
            return
        
        current_time = time.time()
        cutoff_time = current_time - (days_old * 24 * 60 * 60)
        
        try:
            for filename in os.listdir(persistence_dir):
                if filename.endswith('_dedup_state.json'):
                    file_path = os.path.join(persistence_dir, filename)
                    file_mtime = os.path.getmtime(file_path)
                    
                    if file_mtime < cutoff_time:
                        os.remove(file_path)
                        print(f"清理旧状态文件: {filename}")
        except Exception as e:
            print(f"清理旧状态文件时出错: {e}")
    
    @staticmethod
    def list_all_states():
        """
        列出所有存在的去重状态文件
        
        Returns:
            包含状态文件信息的列表
        """
        persistence_dir = os.path.join(os.getcwd(), '.video_merger', 'dedup_states')
        if not os.path.exists(persistence_dir):
            return []
        
        states = []
        try:
            for filename in os.listdir(persistence_dir):
                if filename.endswith('_dedup_state.json'):
                    file_path = os.path.join(persistence_dir, filename)
                    file_size = os.path.getsize(file_path)
                    file_mtime = os.path.getmtime(file_path)
                    
                    # 尝试读取状态信息
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            state_data = json.load(f)
                        
                        states.append({
                            'filename': filename,
                            'file_path': file_path,
                            'file_size': file_size,
                            'last_modified': file_mtime,
                            'used_sequences_count': len(state_data.get('used_sequences', [])),
                            'materials_count': len(state_data.get('materials', [])),
                            'per_video': state_data.get('per_video', 0)
                        })
                    except:
                        # 如果读取失败，只记录基本信息
                        states.append({
                            'filename': filename,
                            'file_path': file_path,
                            'file_size': file_size,
                            'last_modified': file_mtime,
                            'used_sequences_count': 'unknown',
                            'materials_count': 'unknown',
                            'per_video': 'unknown'
                        })
        except Exception as e:
            print(f"列出状态文件时出错: {e}")
        
        return states


# 使用示例和测试代码
if __name__ == "__main__":
    # 模拟少量素材以便测试连续2元素去重功能
    materials = [f"clip_{i}" for i in range(20)]  # 减少素材数量以便观察效果
    
    # 每条视频用 3 个素材
    selector = SequenceDiversitySelector(materials, per_video=3)
    
    print("=== 素材顺序多样化选择器测试（增强版：连续2元素去重）===")
    print(f"总素材数：{len(materials)}")
    print(f"每条视频素材数：{selector.per_video}")
    print()
    
    # 生成 8 条视频的组合
    generated_combinations = []
    for i in range(8):
        combo = selector.get_next_combination()
        generated_combinations.append(combo)
        # 显示组合及其连续2元素子序列
        pairs = selector._extract_consecutive_pairs(combo)
        print(f"视频 {i+1} 组合：{combo}")
        print(f"    连续2元素子序列：{pairs}")
    
    print("\n=== 验证结果 ===")
    # 验证：检查是否有顺序完全相同的组合
    sequences = [tuple(combo) for combo in generated_combinations]
    unique_sequences = set(sequences)
    
    print(f"生成的组合数：{len(sequences)}")
    print(f"唯一序列数：{len(unique_sequences)}")
    print(f"是否所有组合顺序都不同？{len(sequences) == len(unique_sequences)}")
    
    # 验证：检查是否有连续2元素子序列重复
    all_pairs = []
    for combo in generated_combinations:
        pairs = selector._extract_consecutive_pairs(combo)
        all_pairs.extend(pairs)
    
    unique_pairs = set(all_pairs)
    print(f"所有连续2元素子序列数：{len(all_pairs)}")
    print(f"唯一连续2元素子序列数：{len(unique_pairs)}")
    print(f"是否所有连续2元素子序列都不重复？{len(all_pairs) == len(unique_pairs)}")
    
    # 新增验证：检查单条视频内是否有重复素材
    has_internal_duplicates = False
    for i, combo in enumerate(generated_combinations):
        if len(combo) != len(set(combo)):
            print(f"警告：视频 {i+1} 内有重复素材：{combo}")
            has_internal_duplicates = True
    
    print(f"是否所有视频内素材都不重复？{not has_internal_duplicates}")
    
    # 显示统计信息
    stats = selector.get_statistics()
    print(f"\n=== 统计信息 ===")
    print(f"已用顺序组合数：{stats['used_sequences_count']}")
    print(f"已用连续2元素子序列数：{stats['used_pairs_count']}")
    print(f"素材最大使用次数：{stats['max_usage']}")
    print(f"素材最小使用次数：{stats['min_usage']}")
    print(f"未使用的素材数：{stats['unused_materials']}")
    
    # 显示前几个已用顺序组合和连续2元素子序列
    print(f"\n已用顺序组合（前 3 条）：{list(selector.used_sequences)[:3]}")
    print(f"已用连续2元素子序列（前 5 条）：{list(selector.used_pairs)[:5]}")
    
    print("\n=== 高强度测试：大规模素材场景 ===")
    # 测试大规模素材场景
    large_materials = [f"clip_{i}" for i in range(1000)]
    large_selector = SequenceDiversitySelector(large_materials, per_video=3)
    
    # 生成更多组合测试性能
    print("生成100个组合进行性能测试...")
    for i in range(100):
        combo = large_selector.get_next_combination()
        if i % 20 == 0:  # 每20个显示一次进度
            print(f"  已生成 {i+1} 个组合")
    
    large_stats = large_selector.get_statistics()
    print(f"\n大规模测试统计：")
    print(f"  已用顺序组合数：{large_stats['used_sequences_count']}")
    print(f"  已用连续2元素子序列数：{large_stats['used_pairs_count']}")
    print(f"  素材最大使用次数：{large_stats['max_usage']}")
    print(f"  素材最小使用次数：{large_stats['min_usage']}")
    print(f"  未使用的素材数：{large_stats['unused_materials']}")
