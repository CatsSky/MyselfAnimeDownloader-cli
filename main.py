from rich import print
from concurrent.futures import Future, ThreadPoolExecutor
import concurrent.futures
import glob
import logging
from rich.logging import RichHandler
from subprocess import Popen, PIPE, STDOUT
import m3u8
import os
from tqdm import TqdmExperimentalWarning
import concurrent
import shutil
import argparse
# from tqdm.rich import tqdm_rich as tqdm
from tqdm import tqdm
import warnings
from myself import Myself, AnimeTotalInfoTableDict

# ignore tqdm.rich warning about expirimental feature
warnings.filterwarnings("ignore", category=TqdmExperimentalWarning)

# logging settings
FORMAT = "%(message)s"
logging.basicConfig(
    level="WARNING", format=FORMAT, datefmt="[%X]", handlers=[RichHandler()]
)

log = logging.getLogger("rich")

# helper
# https://stackoverflow.com/questions/21953835/run-subprocess-and-print-output-to-logging
def log_subprocess_output(pipe, log_level: int):
    for line in iter(pipe.readline, b''): # b'\n'-separated lines
        log.log(log_level, line)
        
        
def dir_path(string):
    if not os.path.exists(string):
        # check for permission first
        os.makedirs(string)
        return string
    elif os.path.isdir(string):
        return string
    else:
        raise NotADirectoryError(string)




def download_ts(ts_url: str, directory: str, uri: str):
    video_content = Myself.get_content(url=ts_url)
    with open(os.path.join(directory, uri), 'wb') as f:
        f.write(video_content)


def download_episode(thread_id: int, episode_index: int, download_dir: str = '.', threads: int = 8, anime_info: AnimeTotalInfoTableDict | None = None):

    if anime_info is None:
        print('fetching anime info...')
        anime_info = Myself.anime_total_info(url=f'https://Myself-bbs.com/thread-{thread_id}-1-1.html')

    episode_info = anime_info['video'][episode_index]
    merged_mp4 = f'{anime_info["name"]} {episode_info["name"]}.mp4'
    video_url, m3u8_url = Myself.parse_episode_url(episode_info['url'])

    m3u8_obj = m3u8.loads(Myself.get_m3u8_text(m3u8_url))

    
    ts_dir = os.path.join(os.curdir, 'ts', str(thread_id), str(episode_index))
    # TODO: make download resume from last launch
    shutil.rmtree(ts_dir, ignore_errors=True)
    os.makedirs(ts_dir, exist_ok=True)


    log.info(f'Downloading {anime_info["name"]}: {episode_info["name"]}...')
    
    with ThreadPoolExecutor(max_workers=threads) as executor:
        futures: list[Future] = []
        for m3u8_data in m3u8_obj.segments:
            futures.append(executor.submit(
                download_ts,
                ts_url=f'{video_url}/{m3u8_data.uri}', 
                directory=ts_dir, 
                uri=m3u8_data.uri
            ))
        
        with tqdm(total=len(futures), smoothing=0, position=episode_index, desc=f'{episode_info["name"]}') as bar:
            for future in concurrent.futures.as_completed(futures):
                bar.update()
    
    
    log.info(f'{episode_info["name"]} Merging ts files...')
    
    ts_files = sorted(glob.glob(root_dir=ts_dir, pathname='*.ts'))
    with open(os.path.join(ts_dir, 'files.txt'), '+a') as file:
        file.write('\n'.join(map(lambda s: f'file {s}', ts_files)))

    process = Popen([
        'ffmpeg', '-y', '-f', 'concat', '-i', 'files.txt', '-c', 'copy', '-bsf:a', 'aac_adtstoasc', merged_mp4
    ], stdout=PIPE, stderr=STDOUT, cwd=ts_dir)
    
    if process.stdout is not None:
        with process.stdout:
            log_subprocess_output(process.stdout, logging.DEBUG)
        exitcode = process.wait()
    
    
    log.info(f'{episode_info["name"]} moving file to destination...')
    os.makedirs(download_dir, exist_ok=True)
    shutil.move(
        os.path.join(ts_dir, merged_mp4),
        os.path.join(download_dir, merged_mp4)
    )
    
    log.info(f'{episode_info["name"]} Pruning ts files...')
    shutil.rmtree(ts_dir)
    
    log.info(f'{episode_info["name"]} downloaded!')
    
    
def download_anime(thread_id: int, download_dir: str = '.', threads: int = 8, e_threads: int = 4):
    print(f'fetching anime info of {thread_id}...')
    anime_info = Myself.anime_total_info(url=f'https://Myself-bbs.com/thread-{thread_id}-1-1.html')
    episodes = len(anime_info['video'])
    
    download_dir = os.path.join(download_dir, anime_info['name'])
    
    with ThreadPoolExecutor(max_workers=e_threads) as executor:
        for i in range(episodes):
            file_name = f'{anime_info["name"]} {anime_info["video"][i]["name"]}.mp4'
            file_path = os.path.join(download_dir, file_name)
            log.debug(f'testing path {file_path}...')
            
            if os.path.exists(file_path) or os.path.exists(os.path.join(download_dir, f'{anime_info["video"][i]["name"]}.mp4')):
                log.info(f'{file_name} already downloaded, skipped...')
                continue
            
            log.info(f'{anime_info["video"][i]["name"]} not downloaded, proceed to download')
            executor.submit(download_episode, thread_id, i, download_dir, threads, anime_info=anime_info)
            
    
    print(f'finished downloading {anime_info["name"]}')



def _build_dl_parser(subcmd):
    dl_parser = subcmd.add_parser('download',
                                  help='download anime')
    dl_parser.add_argument('thread_id',
                           type=int,
                           help='thread id of the anime, can check it on the website url. It is in the form of "thread-47717-1-1.html" or "forum.php?tid=47717", the id would be 47717')
    dl_parser.add_argument('-e', '--episode-index',
                           type=int,
                           required=False,
                           default=[],
                           nargs='+',
                           help='episode index, if not specified, downloads the whole anime series')
    dl_parser.add_argument('-t', '--threads',
                           type=int,
                           required=False,
                           default=8,
                           help='number of concurrent download threads per episode (Default: 8)')
    dl_parser.add_argument('-c',
                           type=int,
                           required=False,
                           default=4,
                           help='number of episodes downloaded at a time (Default: 4)')
    dl_parser.add_argument('-d', '--download-path',
                           type=dir_path,
                           required=False,
                           default='./download',
                           help='specify the download directory (default: "./download")')

def _build_parser():
    parser = argparse.ArgumentParser(description='Download anime from Myself-bbs.com')
    
    parser.add_argument(
        '-d', '--debug',
        help="Print lots of debugging statements",
        action="store_const", dest="loglevel", const=logging.DEBUG,
        default=logging.WARNING,
    )
    parser.add_argument(
        '-v', '--verbose',
        help="Be verbose",
        action="store_const", dest="loglevel", const=logging.INFO,
    )
    
    # sub commands
    subcmd = parser.add_subparsers(
        dest='subcmd', help='subcommands', metavar='SUBCOMMAND')
    subcmd.required = True

    _build_dl_parser(subcmd)

    return parser



if __name__ == '__main__':
    parser = _build_parser()
    args = parser.parse_args()
    logging.getLogger().setLevel(level=args.loglevel)
    
    log.debug(args)
    
    if args.subcmd == 'download':
        if len(args.episode_index) > 0:
            with ThreadPoolExecutor(max_workers=args.c) as executor:
                for e in args.episode_index:
                    executor.submit(download_episode, args.thread_id, e, download_dir=args.download_path)
        else:
            download_anime(args.thread_id, download_dir=args.download_path, threads=args.threads, e_threads=args.c)
