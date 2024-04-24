from concurrent.futures import Future, ThreadPoolExecutor
import concurrent.futures
import glob
import json
import logging
from rich.logging import RichHandler
import ssl
import subprocess
import m3u8
import requests
import websocket
import os
from contextlib import closing
from functools import reduce
from typing import TypedDict, List, Tuple
from bs4 import BeautifulSoup, Tag
from tqdm import TqdmExperimentalWarning
import concurrent
import shutil
import argparse
from rich import print
from tqdm.rich import tqdm_rich as tqdm
import warnings

# ignore tqdm.rich warning about expirimental feature
warnings.filterwarnings("ignore", category=TqdmExperimentalWarning)

# logging settings
FORMAT = "%(message)s"
logging.basicConfig(
    level="WARNING", format=FORMAT, datefmt="[%X]", handlers=[RichHandler()]
)

log = logging.getLogger("rich")

# http settings
headers = {
    'origin': 'https://v.myself-bbs.com',
    'referer': 'https://v.myself-bbs.com/',
    'User-Agent': 'Mozilla/5.0 (X11; Linux i686; rv:125.0) Gecko/20100101 Firefox/125.0',
}

# websocket 設定
ws_opt = {
    'header': headers,
    'url': "wss://v.myself-bbs.com/ws",
    'host': 'v.myself-bbs.com',
    'origin': 'https://v.myself-bbs.com',
}

# 星期一 ~ 星期日
week = {
    0: 'Monday',
    1: 'Tuesday',
    2: 'Wednesday',
    3: 'Thursday',
    4: 'Friday',
    5: 'Saturday',
    6: 'Sunday',
}

# 動漫資訊的 Key 對照表
anime_table = {
    '作品類型': 'anime_type',
    '首播日期': 'premiere_date',
    '播出集數': 'episode',
    '原著作者': 'author',
    '官方網站': 'official_website',
    '備注': 'remarks',
}


class WeekAnimeItemDict(TypedDict):
    name: str
    url: str
    update_color: str
    color: str
    update: str


class WeekAnimeDict(TypedDict):
    Monday: List[WeekAnimeItemDict]
    Tuesday: List[WeekAnimeItemDict]
    Wednesday: List[WeekAnimeItemDict]
    Thursday: List[WeekAnimeItemDict]
    Friday: List[WeekAnimeItemDict]
    Saturday: List[WeekAnimeItemDict]
    Sunday: List[WeekAnimeItemDict]


class BaseNameUrlTypedDict(TypedDict):
    name: str
    url: str


class AnimeInfoVideoDataDict(BaseNameUrlTypedDict):
    pass


class AnimeInfoTableDict(TypedDict):
    anime_type: str
    premiere_date: str
    episode: str
    author: str
    official_website: str
    synopsis: str
    image: str


class AnimeTotalInfoTableDict(BaseNameUrlTypedDict):
    video: List[AnimeInfoVideoDataDict]


class FinishAnimePageDataDict(BaseNameUrlTypedDict):
    image: str


class FinishListDataDict(TypedDict):
    title: str
    data: List[BaseNameUrlTypedDict]


class FinishListDict(TypedDict):
    data: List[FinishListDataDict]



def bad_name(name: str) -> str:
    """
    避免不正當名字出現導致資料夾或檔案無法創建。

    :param name: 名字。
    :return: '白色相簿2'
    """
    ban = r'\/:*?"<>|'
    return reduce(lambda x, y: x + y if y not in ban else x + ' ', name).strip()



class Myself:
    @staticmethod
    def _req(url: str, timeout: tuple = (5, 5)) -> requests.Response:
        try:
            return requests.get(url=url, headers=headers, timeout=timeout)
        except requests.exceptions.RequestException as error:
            raise ValueError(f'請求有錯誤: {error}')

    @classmethod
    def week_anime(cls) -> WeekAnimeDict:
        """
        爬首頁的每週更新表。

        :return: dict。
        {
            'Monday': [{
                'name': 動漫名字,
                'url': 動漫網址,
                'update_color: 網頁上面"更新"的字體顏色'
                'color': 字體顏色,
                'update': 更新級數文字,
            }, ...],
            'Tuesday': [{...}],
            ...
        }
        """
        res = cls._req(url='https://myself-bbs.com/portal.php')
        data = {}
        if res and res.ok:
            html = BeautifulSoup(res.text, features='lxml')
            if (elements := html.find('div', id='tabSuCvYn')) is Tag:
                for index, elements in enumerate(elements.find_all('div', class_='module cl xl xl1')):
                    animes = []
                    for element in elements:
                        animes.append({
                            'name': element.find('a')['title'],
                            'url': f"https://myself-bbs.com/{element.find('a')['href']}",
                            'update_color': element.find('span').find('font').find('font')['style'],
                            'update': element.find('span').find('font').text,
                        })

                    data.update({
                        week[index]: animes
                    })

        return data

    @staticmethod
    def anime_info_video_data(html: BeautifulSoup) -> List[AnimeInfoVideoDataDict]:
        """
        取得動漫網頁的影片 Api Url。

        :param html: BeautifulSoup 解析的網頁。
        :return: [{name: 第幾集名稱, url: 網址}]
        """
        data = []
        for main_list in html.select('ul.main_list'):
            for a in main_list.find_all('a', href='javascript:;'):
                name = a.text
                for display in a.parent.select('ul.display_none li'):
                    if display.select_one('a').text == '站內':
                        a = display.select_one("a[data-href*='v.myself-bbs.com']")
                        video_url = a['data-href'].replace(
                            'player/play',
                            'vpx',
                        ).replace(
                            '\r',
                            '',
                        ).replace('\n', '')
                        data.append({
                            'name': bad_name(name=name),
                            'url': video_url,
                        })

        return data

    @staticmethod
    def anime_info_table(html: BeautifulSoup) -> AnimeInfoTableDict:
        """
        取得動漫資訊。

        :return: {
            anime_type: 作品類型,
            premiere_date: 首播日期,
            episode: 播出集數,
            author: 原著作者,
            official_website: 官方網站,
            remarks: 備注,
            synopsis: 簡介,
            image: 圖片網址,
        }
        """
        data = {}
        for elements in html.find_all('div', class_='info_info'):
            for element in elements.find_all('li'):
                text = element.text
                key, value = text.split(': ')
                data.update({anime_table[key]: value})

            for element in elements.find_all('p'):
                data.update({'synopsis': element.text})

        for elements in html.find_all('div', class_='info_img_box fl'):
            for element in elements.find_all('img'):
                data.update({'image': element['src']})

        return data

    @classmethod
    def anime_total_info(cls, url: str) -> AnimeTotalInfoTableDict:
        """
        取得動漫頁面全部資訊。

        :param url: str -> 要爬的網址。
        :return: dict -> 動漫資料。
        {
            url: 網址,
            video: [{name: 第幾集名稱, url: 網址}]
            name: 名字,
            anime_type: 作品類型,
            premiere_date: 首播日期,
            episode: 播出集數,
            author: 原著作者,
            official_website: 官方網站,
            remarks: 備注,
            synopsis: 簡介,
            image: 圖片網址,
        }
        """
        res = cls._req(url=url)
        data = {}
        if res and res.ok:
            html = BeautifulSoup(res.text, features='lxml')
            if (title := html.find('title')) is not None:
                data.update(cls.anime_info_table(html=html))
                data.update({
                    'url': url,
                    'name': bad_name(title.text.split('【')[0]),
                    'video': cls.anime_info_video_data(html=html)
                })

        return data

    @classmethod
    def finish_list(cls) -> List[FinishListDict]:
        """
        取得完結列表頁面的動漫資訊。

        :return: [{
            'data': [
                {'title': '2013年10月（秋）','data': [{'name': '白色相簿2', 'url': '動漫網址'}, {...}]},
                {'title': '2013年07月（夏）', 'data': [{...}]}.
                {...},
            ]
        }]
        """
        res = cls._req(url='https://myself-bbs.com/portal.php?mod=topic&topicid=8')
        data = []
        if res and res.ok:
            html = BeautifulSoup(res.text, features='lxml')
            for elements in html.find_all('div', {'class': 'tab-title title column cl'}):
                year_list = []
                for element in elements.find_all('div', {'class': 'block move-span'}):
                    year_month_title = element.find('span', {'class': 'titletext'}).text
                    season_list = []
                    for k in element.find_all('a'):
                        season_list.append({'name': k['title'], 'url': f"https://myself-bbs.com/{k['href']}"})

                    year_list.append({'title': year_month_title, 'data': season_list})

                data.append({'data': year_list})

        return data

    @classmethod
    def finish_anime_page_data(cls, url: str) -> list[FinishAnimePageDataDict]:
        """
        完結動漫頁面的動漫資料。

        :param url: 要爬的網址。
        :return: [{'url': 'https://myself-bbs.com/thread-43773-1-1.html', 'name': '白色相簿2'}, {...}]。
        """
        res = cls._req(url=url)
        data = []
        if res and res.ok:
            html = BeautifulSoup(res.text, 'lxml')
            for elements in html.find_all('div', class_='c cl'):
                data.append({
                    'url': f"https://myself-bbs.com/{elements.find('a')['href']}",
                    'name': bad_name(elements.find('a')['title']),
                    'image': f"https://myself-bbs.com/{elements.find('a').find('img')['src']}"
                })

        return data

    @classmethod
    def get_m3u8_text(cls, url: str, timeout: tuple = (10, 10)) -> str:
        """
        :param url: m3u8 的 Api Url。
        :param timeout: 請求與讀取時間。
        :return: 官網回應 m3u8 格式。
        """
        res = cls._req(url=url, timeout=timeout)
        if res and res.ok:
            return res.text
        raise ValueError('掛了')

    @classmethod
    def get_content(cls, url: str, timeout: tuple = (30, 30)) -> bytes:
        """
        :param url: 影片或圖片的 Url。
        :param timeout: 請求與讀取時間。
        :return: 影片或圖片的格式。
        """
        res = cls._req(url=url, timeout=timeout)
        if res and res.ok:
            return res.content
        raise ValueError('掛了')

    @classmethod
    def ws_get_host_and_m3u8_url(
            cls,
            tid: str,
            vid: str,
            video_id: str,
    ) -> Tuple[str, str]:
        """
        Websocket 取得 Host 和 M3U8 資料。

        :param tid:
        :param vid:
        :param video_id:
        :return: Host, M3U8 的 URL。
        """
        try:
            with closing(websocket.create_connection(**ws_opt)) as ws:
                ws.send(json.dumps({'tid': tid, 'vid': vid, 'id': video_id}))
                recv = ws.recv()
                res = json.loads(recv)
                m3u8_url = f'https:{res["video"]}'
                if video_id:
                    video_url = m3u8_url.split('/index.m3u8')[0]
                else:
                    video_url = m3u8_url[:m3u8_url.rfind('/')]
                return video_url, m3u8_url
        except ssl.SSLCertVerificationError:
            print(f'ssl 憑證有問題: ws_opt: {ws_opt}')

            if 'sslopt' in ws_opt:
                raise ValueError('不知道發生什麼錯誤了!')

            # 有些人電腦會有 SSL 問題，加入 sslopt 設定並重新請求一次。
            ws_opt['sslopt'] = {'cert_reqs': ssl.CERT_NONE}
            return cls.ws_get_host_and_m3u8_url(
                tid=tid,
                vid=vid,
                video_id=video_id,
            )
        except Exception as e:
            raise ValueError(f'websocket 其餘未捕抓問題: {e}')

    @classmethod
    def parse_episode_url(cls, url: str):
        s = url.split('/')

        # 將需要的資料拆解，url 拆解有兩種模式。
        if s[-1].isdigit():
            tid, vid, video_id = s[-2], s[-1], ''
        else:
            tid, vid, video_id = '', '', s[-1]

        return cls.ws_get_host_and_m3u8_url(
            tid=tid,
            vid=vid,
            video_id=video_id,
        )

    @classmethod
    def download_ts(cls, ts_url: str, directory: str, uri: str):
    # def download_ts(cls, arg: tuple[str, str, str]):
        # ts_url, directory, uri = arg
        video_content = cls.get_content(url=ts_url)
        with open(os.path.join(directory, uri), 'wb') as f:
            f.write(video_content)

    @classmethod
    def download_episode(cls, thread_id: int, episode_index: int, download_dir: str = '.', threads: int = 8, anime_info: AnimeTotalInfoTableDict | None = None):

        if anime_info is None:
            print('fetching anime info...')
            anime_info = cls.anime_total_info(url=f'https://myself-bbs.com/thread-{thread_id}-1-1.html')

        episode_info = anime_info['video'][episode_index]
        video_url, m3u8_url = cls.parse_episode_url(episode_info['url'])

        m3u8_obj = m3u8.loads(cls.get_m3u8_text(m3u8_url))

        
        ts_dir = os.path.join(os.curdir, 'ts', str(thread_id), str(episode_index))
        # TODO: make download resume from last launch
        shutil.rmtree(ts_dir, ignore_errors=True)
        os.makedirs(ts_dir, exist_ok=True)

        print(f'Downloading {anime_info["name"]}: {episode_info["name"]}...')
        
        with ThreadPoolExecutor(max_workers=threads) as executor:
            futures:list[Future] = []
            for m3u8_data in m3u8_obj.segments:
                futures.append(executor.submit(
                    cls.download_ts,
                    ts_url=f'{video_url}/{m3u8_data.uri}', 
                    directory=ts_dir, 
                    uri=m3u8_data.uri
                ))
            
            with tqdm(total=len(futures), smoothing=0) as bar:
                for future in concurrent.futures.as_completed(futures):
                    bar.update()
        
        print(f'Merging ts files...')
        
        ts_files = sorted(glob.glob(root_dir=ts_dir, pathname='*.ts'))
        with open(os.path.join(ts_dir, 'files.txt'), '+a') as file:
            file.write('\n'.join(map(lambda s: f'file {s}', ts_files)))
        
        merged_mp4 = f'{anime_info["name"]} {episode_info["name"]}.mp4'
        
        subprocess.run([
            'ffmpeg', '-y', '-f', 'concat', '-i', 'files.txt', '-c', 'copy', '-bsf:a', 'aac_adtstoasc', merged_mp4
        ], cwd=ts_dir)
        
        print(f'Pruning ts files...')
        
        download_dir = os.path.join(download_dir, anime_info['name'])
        os.mkdir(download_dir)
        os.rename(
            os.path.join(ts_dir, merged_mp4),
            os.path.join(download_dir, merged_mp4)
        )
        
        shutil.rmtree(ts_dir)
        
        print(f'Download completed!')
        
    @classmethod
    def download_anime(cls, thread_id: int, download_dir: str = '.', threads: int = 8):
        print('fetching anime info...')
        anime_info = cls.anime_total_info(url=f'https://myself-bbs.com/thread-{thread_id}-1-1.html')
        episodes = len(anime_info['video'])
        
        for i in range(episodes):
            cls.download_episode(thread_id, i, download_dir, threads, anime_info=anime_info)
        


def _build_parser():
    parser = argparse.ArgumentParser(description='Download anime from myself-bbs.com')
    
    subcmd = parser.add_subparsers(
        dest='subcmd', help='subcommands', metavar='SUBCOMMAND')
    subcmd.required = True

    # download
    dl_parser = subcmd.add_parser('download',
                                  aliases=['d', 'dl'],
                                  help='download anime')
    dl_parser.add_argument('thread_id',
                           type=int,
                           help='thread id of the anime, can check it on the website url. It is in the form of "thread-47717-1-1.html" or "forum.php?tid=47717", the id would be 47717')
    dl_parser.add_argument('-e',
                           type=int,
                           required=False,
                           default=None,
                           nargs='+',
                           help='episode index')

    # echo
    echo_parser = subcmd.add_parser('echo',
                                    help='echo a given message')
    echo_parser.add_argument('msg', help='the message', metavar='\'MESSAGE\'')
    
    return parser



if __name__ == '__main__':
    parser = _build_parser()
    args = parser.parse_args()
    
    log.debug(args)
    
    if args.subcmd == 'download':
        if args.e is not None:
            for e in args.e:
                Myself.download_episode(args.thread_id, e, download_dir='./download')
        else:
            Myself.download_anime(args.thread_id, download_dir='./download')
    
