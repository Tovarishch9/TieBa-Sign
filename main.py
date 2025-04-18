# -*- coding:utf-8 -*-
import os
import requests
import hashlib
import time
import copy
import logging
import random
import smtplib
from email.mime.text import MIMEText

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# API_URL
LIKIE_URL = "http://c.tieba.baidu.com/c/f/forum/like"
TBS_URL = "http://tieba.baidu.com/dc/common/tbs"
SIGN_URL = "http://c.tieba.baidu.com/c/c/forum/sign"

ENV = os.environ

HEADERS = {
    'Host': 'tieba.baidu.com',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',  # 更新User-Agent [[1]]
}
SIGN_DATA = {
    '_client_type': '2',
    '_client_version': '9.7.8.0',
    '_phone_imei': '000000000000000',
    'model': 'MI+5',
    "net_type": "1",
}

# VARIABLE NAME
COOKIE = "Cookie"
BDUSS = "BDUSS"
EQUAL = r'='
EMPTY_STR = r''
TBS = 'tbs'
PAGE_NO = 'page_no'
ONE = '1'
TIMESTAMP = "timestamp"
DATA = 'data'
FID = 'fid'
SIGN_KEY = 'tiebaclient!!!'
UTF8 = "utf-8"
SIGN = "sign"
KW = "kw"

s = requests.Session()

def get_tbs(bduss):
    logger.info("获取tbs开始")
    headers = copy.copy(HEADERS)
    headers.update({COOKIE: EMPTY_STR.join([BDUSS, EQUAL, bduss])})
    try:
        res = s.get(url=TBS_URL, headers=headers, timeout=5).json()
        tbs = res.get(TBS, '')  # 防止API结构变化 [[8]]
        if not tbs:
            logger.error(f"TBS字段缺失，API响应: {res}")
            return None
    except Exception as e:
        logger.error(f"获取tbs出错: {e}")
        return None
    logger.info("获取tbs结束")
    return tbs

def get_favorite(bduss):
    logger.info("获取关注的贴吧开始")
    returnData = {'forum_list': {'non-gconforum': [], 'gconforum': []}}
    max_pages = 5  # 最大分页限制防止死循环 [[8]]
    for page_no in range(1, max_pages + 1):
        data = {
            'BDUSS': bduss,
            '_client_type': '2',
            '_client_id': 'wappc_1534235498291_488',
            '_client_version': '9.7.8.0',
            '_phone_imei': '000000000000000',
            'from': '1008621y',
            'page_no': str(page_no),
            'page_size': '200',
            'model': 'MI+5',
            'net_type': '1',
            'timestamp': str(int(time.time())),
            'vcode_tag': '11',
        }
        data = encodeData(data)
        try:
            res = s.post(url=LIKIE_URL, data=data, timeout=5).json()
            if not res.get('forum_list'):
                break
            # 合并数据（兼容新旧API结构）
            for key in ['non-gconforum', 'gconforum']:
                if key in res['forum_list']:
                    returnData['forum_list'][key].extend(res['forum_list'][key])
            if res.get('has_more') != '1':
                break
        except Exception as e:
            logger.error(f"分页{page_no}请求失败: {e}")
            break
    # 展平嵌套列表
    forums = []
    for category in returnData['forum_list'].values():
        for item in category:
            if isinstance(item, list):
                forums.extend([i for i in item if isinstance(i, dict)])
            elif isinstance(item, dict):
                forums.append(item)
    logger.info(f"共获取{len(forums)}个贴吧")
    return forums

def encodeData(data):
    s = EMPTY_STR
    keys = sorted(data.keys())
    for k in keys:
        s += f"{k}={data[k]}"
    sign = hashlib.md5((s + SIGN_KEY).encode(UTF8)).hexdigest().upper()
    data.update({SIGN: sign})
    return data

def client_sign(bduss, tbs, fid, kw, max_retries=3):
    logger.info(f"开始签到贴吧：{kw}")
    data = copy.copy(SIGN_DATA)
    data.update({
        'BDUSS': bduss,
        FID: fid,
        KW: kw,
        TBS: tbs,
        TIMESTAMP: str(int(time.time()))
    })
    data = encodeData(data)
    for retry in range(max_retries):
        try:
            res = s.post(SIGN_URL, data=data, timeout=5).json()
            if res.get('error_code', '') == '0':
                logger.info(f"签到成功: {kw}")
                return True
            else:
                logger.warning(f"签到失败({res.get('error_code')}): {res.get('error_msg')}")
        except Exception as e:
            logger.error(f"请求异常: {e}")
        time.sleep(2 ** retry)  # 指数退避 [[7]]
    return False

def send_email(sign_list):
    required_env = ['HOST', 'FROM', 'TO', 'AUTH']
    if not all(k in ENV for k in required_env):
        logger.error(f"邮件配置缺失: {', '.join(required_env)}")
        return
    HOST = ENV['HOST']
    FROM = ENV['FROM']
    TO = ENV['TO'].split('#')
    AUTH = ENV['AUTH']
    
    # 安全处理字段缺失 [[6]]
    body = """
    <style>.child{background:rgba(173,216,230,0.19);padding:10px}
    .child *{margin:5px}</style>
    """
    for forum in sign_list:
        name = forum.get('name', '未知贴吧')
        slogan = forum.get('slogan', '无简介')
        body += f"""
        <div class="child">
            <div class="name">贴吧名称: {name}</div>
            <div class="slogan">贴吧简介: {slogan}</div>
        </div><hr>
        """
    msg = MIMEText(body, 'html', 'utf-8')
    msg['Subject'] = f"{time.strftime('%Y-%m-%d')} 签到{len(sign_list)}个贴吧"
    
    try:
        with smtplib.SMTP(HOST) as smtp:
            smtp.login(FROM, AUTH)
            smtp.sendmail(FROM, TO, msg.as_string())
        logger.info("邮件发送成功")
    except Exception as e:
        logger.error(f"邮件发送失败: {e}")

def main():
    bduss_list = ENV.get('BDUSS', '').split('#')
    if not bduss_list:
        logger.error("未配置BDUSS")
        return
    for n, bduss in enumerate(bduss_list):
        logger.info(f"开始签到第{n+1}个用户")
        tbs = get_tbs(bduss)
        if not tbs:
            continue
        favorites = get_favorite(bduss)
        success_list = []
        for forum in favorites:
            if client_sign(bduss, tbs, forum.get('id', ''), forum.get('name', '')):
                success_list.append(forum)
            time.sleep(random.randint(1,5))
        send_email(success_list)
        logger.info(f"第{n+1}个用户完成{len(success_list)}个贴吧签到")
    logger.info("所有用户签到结束")

if __name__ == '__main__':
    main()
