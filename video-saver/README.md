# 视频提取（video-saver）

本地运行的视频 / 图文提取下载站：粘贴分享链接 → 解析 → 预览 → 一键下载无水印视频，图文自动打包为 ZIP。

毛玻璃质感界面，中文，无第三方 CDN、无 Node 依赖。

## 快速开始

```bash
cd video-saver
pip install -r requirements.txt
python app.py
```

浏览器打开 <http://127.0.0.1:5000>，粘贴分享链接（整段分享文案也可以）即可解析下载。

下载的文件保存在 `downloads/` 目录。

## 支持平台

- **抖音**：专用解析器（任意链接规整为作品 ID → 移动端分享页内嵌数据 → 无水印直链），支持视频与图文；解析失败自动降级 yt-dlp
- **其他**：B站、快手、微博、小红书、西瓜视频、YouTube、TikTok 等，由 yt-dlp 通用引擎处理

## 抖音 Cookie（可选）

抖音对未登录内容有反爬限制。遇到解析失败时：

1. 用浏览器扩展（如 "Get cookies.txt LOCALLY"）导出 `cookies.txt`（Netscape 格式）
2. 在页面点击「需要 Cookie？」，选择文件上传
3. 重新解析

Cookie 仅保存在服务内存中，重启服务后需重新上传。

## 目录结构

```
video-saver/
├── app.py               # Flask 入口 + API
├── engines/
│   ├── douyin.py        # 抖音专用解析器
│   └── ytdlp.py         # yt-dlp 通用引擎
├── downloader.py        # 后台下载编排
├── utils.py             # 链接提取 / 平台识别 / 文件名清洗
├── static/              # 前端（原生 HTML/CSS/JS）
└── downloads/           # 下载文件输出目录
```

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/parse` | 解析分享文本，返回元信息（标题/封面/类型/直链） |
| POST | `/api/download` | 创建后台下载任务 |
| GET  | `/api/task/<id>` | 查询下载进度 |
| GET  | `/api/files/<name>` | 下载已保存的文件 |
| POST | `/api/cookies` | 上传 cookies.txt（Netscape 格式） |
| GET  | `/api/proxy?url=` | 图片代理（抖音封面防盗链） |

## 说明与注意事项

- 视频直链下载，无需 FFmpeg；如需在 yt-dlp 场景下合并音画、获取更高画质，可自行安装 FFmpeg 并加入系统 PATH。
- 抖音反爬规则经常调整：若解析失败，界面会给出提示，建议上传 Cookie 重试；代码结构预留了引擎接口，后续可扩展 Playwright 等更抗反爬的方案。
- 仅用于个人合法内容存档，请遵守各平台服务条款与版权规定。
