# Pushover 通知サービス

このリポジトリは **Pushover を利用して定期通知を送信する軽量な Python
サービス**です。\
常時稼働する環境（例：Render）で動作することを想定しており、HTTP
エンドポイントや cron から簡単に制御できます。\
通知は **Pushover アプリ経由で iPhone / Apple Watch に届きます。**

------------------------------------------------------------------------

# 概要

このサービスは以下の 2 つのコンポーネントで構成されています。

## 1. Flask Web アプリ (`app.py`)

以下の機能を提供します。

-   通知の **開始 / 停止**
-   **通知モード切替**
-   現在の状態取得
-   テスト通知送信

内部では SQLite データベースを使用し、`settings` テーブルの 1
行で以下を管理します。

    enabled   通知ON/OFF
    mode      通知モード

またバックグラウンドスケジューラが動作し、指定時刻に通知を送信します。

------------------------------------------------------------------------

## 2. スタンドアロン通知スクリプト (`notifier.py`)

cron などの外部スケジューラと連携するためのスクリプトです。

このスクリプトは SQLite DB を読み取り

-   enabled
-   mode

を確認し、必要な場合のみ通知を送信します。

つまり以下どちらでも動作できます。

    Flask内スケジューラ
    または
    cron + notifier.py

------------------------------------------------------------------------

# 通知モード

  モード    通知時刻            内容
  --------- ------------------- ------------------
  pomo      00 / 30             HH:MM 作業開始
            25 / 55             HH:MM 休憩開始
  quarter   00 / 15 / 30 / 45   HH:MM の通知です

時間は **Asia/Tokyo (UTC+9)** で計算されます。

------------------------------------------------------------------------

# API エンドポイント

状態変更系 API には **CONTROL_KEY** が必要です。

    ?key=YOUR_CONTROL_KEY

## 通知制御

  URL             説明
  --------------- ------------------
  /start          通知開始
  /stop           通知停止
  /mode/pomo      ポモドーロモード
  /mode/quarter   15分通知モード
  /test           即時通知送信

## 認証不要

  URL       説明
  --------- ------------------------
  /status   現在の設定をJSONで返す
  /ping     ヘルスチェック

------------------------------------------------------------------------

# 環境変数

`.env.example` を `.env` にコピーして設定します。

必須:

    PUSHOVER_USER
    PUSHOVER_TOKEN
    CONTROL_KEY

オプション:

    UPTIMEROBOT_API_KEY
    UPTIMEROBOT_MONITOR_ID
    APP_DB
    PORT

------------------------------------------------------------------------

# 起動方法

## 1 依存関係インストール

    python -m venv venv
    venv\Scripts\activate
    pip install -r requirements.txt

## 2 .env 作成

    copy .env.example .env

必要な値を設定してください。

## 3 サーバ起動

    python app.py

初回起動時に SQLite DB が自動生成されます。

------------------------------------------------------------------------

# UptimeRobot（Renderスリープ対策）

Render の無料プランは 15 分でスリープします。

そのため UptimeRobot を使って

    /ping

を定期的に叩くことでスリープを防げます。

------------------------------------------------------------------------

# iPhone / Apple Watch 操作

以下 URL をショートカットに登録するとワンタップ操作できます。

通知開始

    https://your-app.onrender.com/start?key=CONTROL_KEY

通知停止

    https://your-app.onrender.com/stop?key=CONTROL_KEY

ポモドーロ

    https://your-app.onrender.com/mode/pomo?key=CONTROL_KEY

15分通知

    https://your-app.onrender.com/mode/quarter?key=CONTROL_KEY

------------------------------------------------------------------------

# cron を使う場合

    0,15,25,30,45,55 * * * *

    python notifier.py

------------------------------------------------------------------------

# License

MIT License
