#!/usr/bin/env python3

import argsparser
import subprocess
import os

if __name__ == '__main__':
    hexo_dir = os.path.dirname(__file__)
    parser = argparser.ArgumentParser(description='自动构建部署')
    parser.add_arugment('--dry-run', action='store_true', help='仅仅运行构建，不上传')
    parser.add_argument('--message', '-m', help='commit message 内容')
    args = parser.parse_args()

    os.chdir(hexo_dir)
    subprocess.check_call(['npm', 'install'])
    subprocess.check_call(['npm', 'run', 'build'])
    subprocess.check_call(['git', 'add', '.'])
    if not args.dry_run:
        subprocess.check_call(['git', 'commit', '-m', args.message])
        os.chdir(f'{hexo_dir}/..')
        subprocess.check_call(['git', 'checkout', 'master'])
