# eeg analysis libraries
print("importing EEG libraries")
import mne
from scipy import io
import pkg_resources
import argparse
import ssvepy
from ssvepy import Ssvep, load_ssvep
from ssvepy import frequencymaths
__version__ = pkg_resources.get_distribution("ssvepy").version


# import plotting libraries
print("importing plotting libraries")
import matplotlib
matplotlib.use('Agg')  
import matplotlib.pyplot as plt
import seaborn as sns
from plotnine import *

# numerical libraries
print("importing numerical libraries")
import numpy as np
import pandas as pd
from pandas.plotting import table
import imgkit
  
# import file path operators
print("importing file operators libraries")
from pathlib import Path
import os
import six
from autoreject import AutoReject
from autoreject import Ransac
import fooof 
import xarray as xr

def match_peaks(frequency, fooof_object, max_harmonics=3):

    frequencies = [frequency] + [frequency * i for i in range(2, 2 + max_harmonics)]
    peak_params = fooof_object.peak_params_

    # we should already cut out any peaks that have a high bandwidth:
    peak_params = peak_params[peak_params[:, 2] < 1]
    peaks_inclusion_min = peak_params[:, 0] - 0.25
    peaks_inclusion_max = peak_params[:, 0] + 0.25

    amps = []
    for frequency in frequencies:
        if not fooof_object.freq_range[0] < frequency < fooof_object.freq_range[1]:
            continue

        matches = (peaks_inclusion_min < frequency) & (peaks_inclusion_max > frequency)
        amp = peak_params[matches, 1]
        if amp.size > 0:
            amps.append(amp.squeeze().max().item())
    return sum(amps)

def preprocessing(file):
    print("setting default objects")
    # avoid MNE being too verbose
    mne.set_log_level('ERROR')
    use_autoreject = True
    electrodes_snr = []
    ssveps = []
    snrs_faces = []
    snrs_ob = []
    Report_pp = []

    fooof_object = fooof.FOOOF(
    background_mode='fixed', 
    )
  
    #Start file by file analysis 
    print("reading raw EDF")
    raw = mne.io.read_raw_edf(
        file, montage=mne.channels.read_montage('biosemi64'),eog=[f'EXG{n}' for n in range(1, 9)]
    )
    raw.info['subject_info'] = {
        'pid': file.name[7:11],
        'group': file.name[3:6],
        'filename' :file.name
    }

    # make raw plots 
    file_id = raw.info['subject_info']['filename']
    pid = raw.info['subject_info']['pid']
    path = ('FOOOF/%s' %(pid))

    if not os.path.exists(path):
        os.makedirs(path)

    plot = raw.plot_psd()
    plot.savefig('%s/rawplot_psd_%s.png' %(path, file_id))
    plot.clf()
    plot = raw.plot(duration=30., start=60., block=True)
    plot.savefig('%s/rawplot_%s.png' %(path, file_id))
    plot.clf()

    #Define Events
    events = mne.find_events(raw)
    events = events[events[:, 2] < 255, :]

    raw.info['events'] = mne.find_events(raw, stim_channel='STI 014')

    epochs = (
        mne.Epochs(
            raw,
            events,
            tmin=-1,
            tmax=15,
            preload=True,
        )
        .set_eeg_reference()
        .load_data()
        .resample(256)
        .apply_proj()
    )

    #Evoked Plots 
    evoked = epochs.average()
    fig = mne.viz.plot_evoked(evoked, spatial_colors = True, selectable=True)
    fig.savefig('%s/evoked_plot_%s.png' %(path, file_id))
    fig.clf()

    if use_autoreject:
        #assess sensors 
        print("Running ransac autoreject")
        picks = mne.pick_types(epochs.info, eeg=True,)
        ransac = Ransac(verbose=False, picks=picks, n_jobs=1)
        epochs = ransac.fit_transform(epochs)

    ssvep = ssvepy.Ssvep(
        epochs,
        [1.2, 6],
        compute_tfr=False,
        fmin=0.5,
        fmax=45,
        noisebandwidth=3,
    )

    ssvep.psd = (
        ssvep.psd
        .groupby(ssvep.psd.coords["epoch"] < 200)
        .mean("epoch")
        .rename({"epoch": "faces"})
    )
    ssvep.snr = ssvep._get_snr(ssvep.psd.coords["frequency"].data)
    ssvep.original_psd = ssvep.psd.copy()

    import scipy.linalg

    fooof_data = xr.Dataset(
        {key: xr.full_like(ssvep.psd.interp(frequency=[1.2, 6]), np.nan) 
         for key in ['peak_amp', 'r_squared', 'offset', 'slope']}
    )

    for faces_present, cond_data in ssvep.psd.groupby("faces"):

        for channel, data in cond_data.groupby("channel"):

            try:
                print("Running fooof on channel: {}".format(channel))
                fooof_object.fit(data.coords["frequency"].data, data.data.squeeze())
            except scipy.linalg.LinAlgError:
                print(" Fooof_object failed for %s" %(file_id))
                continue

            ssvep.psd.loc[faces_present, channel, :] -= (10 ** fooof_object._bg_fit)

            fooof_data.peak_amp.loc[faces_present, channel, 1.2] = match_peaks(1.2, fooof_object, max_harmonics=3)
            fooof_data.peak_amp.loc[faces_present, channel, 6] = match_peaks(6, fooof_object, max_harmonics=3)
            fooof_data.r_squared.loc[faces_present, channel, :] = fooof_object.r_squared_
            fooof_data.offset.loc[faces_present, channel, :] = fooof_object.background_params_[0]
            fooof_data.slope.loc[faces_present, channel, :] = fooof_object.background_params_[1]
            
    # average the SNRs:
    snr_data = xr.concat(
        (
            ssvep.snr
            .interp(frequency=[1.2, 2.4, 3.6])
            .mean("frequency")
            .expand_dims(dim={"frequency": [1.2]})
            .transpose("faces", "channel", "frequency"),
            ssvep.snr
            .interp(frequency=[6, 12, 18])
            .mean("frequency")
            .expand_dims(dim={"frequency": [6]})
            .transpose("faces", "channel", "frequency")
        ),
        "frequency"
    )

    # convert to df
    participant_df = (
        pd.merge(
            snr_data.to_dataframe(name='snr').reset_index(),
            fooof_data.to_dataframe().reset_index(),
            on=['frequency', 'faces', 'channel']
        )
        .assign(
            participant=raw.info['subject_info']['pid'],
            group=raw.info['subject_info']['group'],
        )
    )
    
    participant_df.to_csv(
        '%s/output_%s.csv'%(path, file_id), header = True
    )
    
parser = argparse.ArgumentParser(description='pre-process files')
parser.add_argument('file', type=Path, help='input raw eeg file')
args=parser.parse_args()

preprocessing(args.file)

