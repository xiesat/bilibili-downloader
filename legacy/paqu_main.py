import requests
import json
import pprint
import os
from lxml import etree



headers = {
        'Referer': 'https://www.bilibili.com/',
        'Cookie': '<在此填写你自己的 Cookie，切勿提交到版本库>',
        'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0'}


def req(url,headers):
    
    response = requests.get(url=url,headers=headers)
    return response.text

def fen_xi(page_text):

    # print(page_text)
    tree = etree.HTML(page_text)
    title = tree.xpath('//*[@id="viewbox_report"]/div[1]/div[1]/h1/text()')[0]
    play_info = tree.xpath('/html/head/script[4]')[0].text      # 通过tree.xpath得到script对象，然后通过text属性得到其内容
    play_info = play_info[20:]      # 去掉前面的window.__playinfo__=这几个字符
    # print(1)
    # print(title)

    play_info_json = json.loads(play_info)
    # pprint.pprint(play_info_json)   
    video_url = play_info_json['data']['dash']['video'][0]['baseUrl']   
    audio_url = play_info_json['data']['dash']['audio'][0]['baseUrl']  

    video_content = requests.get(url=video_url, headers=headers).content   # content表示二进制数据
    audio_content = requests.get(url=audio_url, headers=headers).content		#  # content表示二进制数据
    return title,video_content,audio_content

def down(btva):
    if not os.path.exists(btva[3]):
        os.mkdir(btva[3])

    with open(btva[3]+'/'+btva[0]+'.mp4', 'wb') as fp:
        fp.write(btva[1])

    with open(btva[3]+'/'+btva[0]+'.mp3', 'wb') as fp:
        fp.write(btva[2])
