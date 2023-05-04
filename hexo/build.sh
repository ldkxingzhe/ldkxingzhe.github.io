#!/usr/bin/env bash

set -e

npm install
npm run build
if [[ -nz $1 ]]; then
	echo "自动发版"
	git add .
	git commit -m $1
	cd ../
	git checkout master
	cp -r hexo/public/* .
	git add .
	git commit -m $1
	git push
fi
