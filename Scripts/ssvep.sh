#!/bin/bash
echo "loading environment"
source /home/rb643/anaconda3/bin/activate
python --version

export XDG_RUNTIME_DIR=/lustre/scratch/wbic-beta/rb643/temp

file=$1
baseDir=/lustre/archive/q10008/Raw 

echo 'running python'  
python /lustre/archive/q10008/Code/Batch_files/MNE_PP_Batch.py ${baseDir}/${file}
