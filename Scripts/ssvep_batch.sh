#!/bin/bash
topDir=/lustre/archive/q10008/Code/Batch_files

# change to your subject list

for sub in `cat subjects_OB.txt` ; do
#for sub in 'CTR-0063' ; do

file=EG-${sub}-Face-Categorisation.bdf

  #baseDir=/lustre/archive/q10008/Raw
  baseDir=/lustre/archive/q10008/Faces/EEG_SSVEP_Faces_OB_Renamed

  if [ -e ${baseDir}/${file} ]
    then

    echo '------------------------------------ working on' ${file} '-----------------------------------'

     sbatch --output=/lustre/archive/q10008/Logs/${file}.log --nodes=1 --ntasks=1 --cpus-per-task=1 --time=02:00:00 --mem=8000 ssvep.sh ${file}

    else

    echo '------------------------------------' ${file}  'does not exist -----------------------------------'

    fi

done
