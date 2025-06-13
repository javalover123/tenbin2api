import requests
import time

def getTaskId():
    url = "http://127.0.0.1:5000/turnstile?url=https://tenbin.ai/workspace&sitekey=0x4AAAAAABGR2exxRproizri&action=issue_execution_token"

    response = requests.get(url)
    response.raise_for_status()
    return response.json()['task_id']

def getCaptcha(task_id):

    url = f"http://127.0.0.1:5000/result?id={task_id}"
    
    while True:
        try:
            response = requests.get(url)
            response.raise_for_status()
            captcha = response.json().get('value', None)
            if captcha:
                return captcha
            else:
                time.sleep(1)
        except Exception as e:
            print(e)
            time.sleep(1)