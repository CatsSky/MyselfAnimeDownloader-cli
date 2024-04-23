# MyselfAnimeDownloader-cli

This application is based on the work of [hgalytoby/MyselfAnimeDownloader](https://github.com/hgalytoby/MyselfAnimeDownloader)

## Usage

This app relies on ffmpeg to merge downloaded m3u8 ts files to a single mp4 file, thus ffmpeg is assumed to be present in PATH.

Install the dependancy

```sh
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Running

```sh
python ./myself.py download thread_id [-e episode_1 [episode_2 ...]]
```

Run `python ./myself.py -h` for more
