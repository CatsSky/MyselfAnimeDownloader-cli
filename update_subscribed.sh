#!/bin/bash

source ./venv/bin/activate

array=($(cat ./subscribed.txt))

for id in "${array[@]}"; do
	python ./main.py download -d /net/truenas.lan/mnt/main/hank/Anime "$id"
done

deactivate
