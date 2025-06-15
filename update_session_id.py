#!/usr/bin/env python3
import os
import json
import argparse
import sys
from datetime import datetime

def create_session_json(session_id, output_file, pretty_print=True):
    """
    创建包含 session_id 的 JSON 文件
    
    参数:
        session_id: 要写入的 session_id 值
        output_file: 输出文件路径
        pretty_print: 是否格式化输出（默认为 True）
    """
    # 创建数据结构
    data = [
        {
            "session_id": session_id,
            "created_at": datetime.utcnow().isoformat() + "Z",  # 添加时间戳
            "source": "generated_by_python_script"  # 添加元数据
        }
    ]
    
    # 确保输出目录存在
    output_dir = os.path.dirname(output_file)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)
    
    try:
        # 写入文件
        with open(output_file, 'w') as f:
            if pretty_print:
                json.dump(data, f, indent=4, ensure_ascii=False)
                f.write('\n')  # 添加换行符
            else:
                json.dump(data, f, separators=(',', ':'), ensure_ascii=False)
        
        print(f"成功创建 JSON 文件: {output_file}")
        print(f"Session ID: {session_id}")
        return True
    
    except Exception as e:
        print(f"写入文件失败: {str(e)}")
        return False

if __name__ == "__main__":
    # 设置命令行参数解析
    parser = argparse.ArgumentParser(
        description='从环境变量创建 session_id JSON 文件',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument('-o', '--output', default='tenbin.json',
                        help='输出文件路径')
    parser.add_argument('-e', '--env-var', default='SESSION_ID',
                        help='环境变量名称')
    parser.add_argument('-m', '--minify', action='store_true',
                        help='生成压缩格式的 JSON（无缩进）')
    parser.add_argument('-v', '--value', 
                        help='直接指定 session_id 值（覆盖环境变量）')
    
    args = parser.parse_args()
    
    # 获取 session_id 值
    if args.value:
        session_id = args.value
    else:
        session_id = os.getenv(args.env_var)
        if not session_id:
            print(f"错误: 未提供 session_id 且环境变量 {args.env_var} 未设置")
            sys.exit(1)
    
    # 创建 JSON 文件
    success = create_session_json(
        session_id=session_id,
        output_file=args.output,
        pretty_print=not args.minify
    )
    
    # 退出状态
    sys.exit(0 if success else 1)
