# tenbin2api，感谢 linux.do 的大佬们

## 生成 session id，放到 tenbin.json

<https://oshiete.deno.dev/>，来源 [oshiete 小日子AI注册机](https://linux.do/t/topic/719206)

## 准备环境

-   新开一个 PowerShell窗口
-   git clone <https://github.com/javalover123/tenbin2api.git>
-   cd tenbin2api
-   python -m venv venv (python要3.8+)
-   venv\Scripts\activate
-   pip install -r requirements.txt
-   python -m patchright install chromium
-   python api_solver.py
-   新开一个 PowerShell窗口，执行 venv\Scripts\activate，然后执行 python main2.py
-   客户端使用 <http://127.0.0.1:8000/v1/models> 获取模型列表，API KEY 从 client_api_keys.json 获取

来源：[【AI平权-授人以渔 18】tenbin2api 每日免费80次高级模型，都给我站起来蹬！](https://linux.do/t/topic/718649)

## Docker

``` bash
git clone https://github.com/javalover123/tenbin2api.git
cd tenbin2api
docker build -t javalover123/tenbin2api:latest .
docker run -d --name tenbin2api -p 8111:8000 -p 5001:5000 -e SESSION_ID=XXXX javalover123/tenbin2api:latest
```
