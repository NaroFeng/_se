# hw1-curl — 從殼層到底層,重新理解 HTTP

> 現代軟體工程 · HW1 · 用三個版本重新理解 HTTP 協定

## 🌐 完整內容請看網頁版

這份 README 只是入口,**真正的內容(包含 HTTP 封包圖解、`curl -v` 真實抓封包動畫、教學流程圖)在網頁版**:

👉 **[https://NaroFeng.github.io/_se/HW-01-curl/](https://NaroFeng.github.io/_se/HW-01-curl/)** ← 部署後填入

網頁版包含:
- HTTP request / response 拆解(彩色高亮 method / path / headers)
- `curl -v` 真實抓封包的動畫演示
- 三版本從黑盒子到白盒子的設計理念
- OSI / TCP / TLS 分層示意圖
- 33 個測試的視覺化呈現

---

## ⚡ 這個 repo 在做什麼

作業題目是「寫一個 curl」,但真正的目的是理解 HTTP 在幹嘛。所以我們用三個版本,從三個不同高度看同一個 GET request:

| 版本 | 工具 | 語言 | 底層 |
|---|---|---|---|
| `fetch.sh` | `curl` | Bash | 別人寫好的 C 執行檔 |
| `fetch_raw.py` | `socket` + `ssl` | Python | 自己開 TCP / TLS / 組 HTTP |
| `fetch_raw.ps1` | `TcpClient` + `SslStream` | PowerShell | 同上,換 .NET |

v2 / v3 的邏輯**完全一樣** — 證明 HTTP 協定本身跟語言無關。

---

## 🚀 快速上手

每個版本用法相同:`fetch 資源 [id]`

```bash
# v1: 透過 curl
./fetch.sh posts 1

# v2: 自己拼 socket
python fetch_raw.py posts 1

# v3: 透過 .NET
powershell -ExecutionPolicy Bypass -File .\fetch_raw.ps1 posts 1
```

## ✅ 跑測試

```bash
./tests/test_fetch.sh                                # 10 個 shell 測試
python -m unittest discover -s tests -p "test_fetch_raw.py" -v   # 9 個 python 測試
./tests/test_fetch_raw.sh                            # 14 個 powershell 測試
```

## 📁 檔案結構

```
hw1-curl/
├── index.html              ← 網頁版(部署到 GitHub Pages)
├── style.css
├── assets/
│   └── curl-v-animation.gif
├── fetch.sh                ← v1: Bash + curl
├── fetch_raw.py            ← v2: Python + socket
├── fetch_raw.ps1           ← v3: PowerShell + .NET
├── lib/
│   ├── api.sh
│   └── http_client.py
└── tests/
    ├── test_fetch.sh
    ├── test_fetch_raw.py
    └── test_fetch_raw.sh
```

---

## 📚 延伸閱讀

網頁版的 [參考資料區塊](https://你的帳號.github.io/hw1-curl/#refs) 列出 RFC 7230/7231 (HTTP/1.1)、RFC 8446 (TLS 1.3) 與 Python 官方 socket 文件。

## 📝 License

MIT
