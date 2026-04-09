import os
import re
import secrets
import sqlite3
import time
from collections import OrderedDict
from contextlib import closing
from datetime import date, datetime, timedelta
from functools import wraps
from html import escape
from pathlib import Path
from urllib.parse import urlencode

from flask import abort, redirect, render_template_string, request, session, url_for
from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("WEIGHT_DB_PATH", str(BASE_DIR / "weight_records.db")))
RATE_LIMITS: dict[str, list[float]] = {}


def env_bool(name: str, default: bool = False) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.lower() in {"1", "true", "yes", "on"}


def require_secret_key() -> str:
    secret_key = os.getenv("SECRET_KEY")
    if secret_key:
        return secret_key
    return "weight-app-local-secret-key-2026-04-08"


app = Flask(__name__)
app.config.update(
    SECRET_KEY=require_secret_key(),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE=os.getenv("SESSION_COOKIE_SAMESITE", "Lax"),
    SESSION_COOKIE_SECURE=env_bool("SESSION_COOKIE_SECURE", False),
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
    REGISTRATION_ENABLED=env_bool("REGISTRATION_ENABLED", True),
    REGISTER_INVITE_CODE=os.getenv("REGISTER_INVITE_CODE", ""),
    INVITE_ADMIN_KEY=os.getenv("INVITE_ADMIN_KEY", ""),
    ADMIN_USERNAME=os.getenv("ADMIN_USERNAME", "root"),
    ADMIN_PASSWORD=os.getenv("ADMIN_PASSWORD", "Joeye2007"),
    CSRF_ENABLED=env_bool("CSRF_ENABLED", True),
    RATE_LIMIT_ATTEMPTS=int(os.getenv("RATE_LIMIT_ATTEMPTS", "8")),
    RATE_LIMIT_WINDOW_SECONDS=int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "300")),
)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

AUTH_TEMPLATE = """
<!doctype html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>体重记录</title>
    <style>
        :root {
            color-scheme: light;
            --bg: #eef3f7;
            --card: #ffffff;
            --primary: #0f766e;
            --primary-hover: #0b5f59;
            --primary-soft: #d9f3ef;
            --muted: #5f6f6c;
            --border: #d6e0e5;
            --text: #12201c;
            --shadow: 0 18px 40px rgba(18, 32, 28, 0.08);
        }

        * { box-sizing: border-box; }

        body {
            margin: 0;
            min-height: 100vh;
            display: grid;
            place-items: center;
            padding: 24px;
            background: var(--bg);
            color: var(--text);
            font-family: "Inter", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
            line-height: 1.5;
            -webkit-text-size-adjust: 100%;
        }

        .shell {
            width: min(960px, 100%);
            display: grid;
            grid-template-columns: 1.1fr 1fr;
            gap: 16px;
            align-items: stretch;
        }

        .card {
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: 14px;
            padding: 28px;
            box-shadow: var(--shadow);
        }

        .intro {
            display: grid;
            align-content: space-between;
            gap: 28px;
            background: #0f766e;
            color: #fff;
            border-color: #0f766e;
        }

        h1, h2 {
            margin: 0 0 12px;
            line-height: 1.2;
        }

        h1 {
            font-size: 34px;
        }

        h2 {
            font-size: 22px;
        }

        .subtitle, .helper {
            color: var(--muted);
            margin: 0 0 14px;
        }

        .intro .subtitle,
        .intro .helper {
            color: rgba(255, 255, 255, 0.82);
        }

        .feature-list {
            display: grid;
            gap: 10px;
            margin: 0;
            padding: 0;
            list-style: none;
        }

        .feature-list li {
            padding: 10px 12px;
            border: 1px solid rgba(255, 255, 255, 0.22);
            border-radius: 8px;
            background: rgba(255, 255, 255, 0.08);
        }

        form + .form-title {
            margin-top: 24px;
        }

        label {
            display: block;
            margin-bottom: 14px;
            color: var(--muted);
            font-size: 14px;
            font-weight: 700;
        }

        input, button {
            width: 100%;
            min-height: 48px;
            margin-top: 6px;
            border-radius: 12px;
            padding: 12px 14px;
            font: inherit;
            font-size: 16px;
        }

        input {
            border: 1px solid var(--border);
            background: #fff;
            color: var(--text);
            outline: none;
            transition: border-color 140ms ease, box-shadow 140ms ease;
        }

        input:focus {
            border-color: var(--primary);
            box-shadow: 0 0 0 3px rgba(15, 118, 110, 0.14);
        }

        .password-field {
            position: relative;
            margin-top: 6px;
        }

        .password-field input {
            margin-top: 0;
            padding-right: 72px;
        }

        .password-toggle {
            position: absolute;
            top: 50%;
            right: 8px;
            width: auto;
            min-width: 52px;
            min-height: 36px;
            margin: 0;
            padding: 7px 10px;
            border: 1px solid var(--border);
            border-radius: 6px;
            background: var(--surface, #f8fafc);
            color: var(--primary);
            font-size: 13px;
            line-height: 1;
            transform: translateY(-50%);
        }

        .password-toggle:hover {
            background: var(--primary-soft);
        }

        .password-toggle:active {
            transform: translateY(calc(-50% + 1px));
        }

        button {
            border: none;
            background: var(--primary);
            color: #fff;
            font-weight: 700;
            cursor: pointer;
            transition: background 140ms ease, transform 140ms ease;
            touch-action: manipulation;
        }

        button:hover {
            background: var(--primary-hover);
        }

        button:active {
            transform: translateY(1px);
        }

        .message {
            margin-bottom: 16px;
            padding: 12px 14px;
            background: #fff7ed;
            border: 1px solid #fed7aa;
            border-radius: 8px;
            color: #9a3412;
        }

        .muted-note {
            margin-top: 20px;
            margin-bottom: 0;
        }

        .inline-link {
            color: var(--primary);
            font-weight: 700;
            text-decoration: none;
        }

        .inline-link:hover {
            text-decoration: underline;
        }

        .intro .inline-link {
            color: #fff;
        }

        @media (max-width: 780px) {
            body {
                padding: 12px;
            }

            .shell {
                grid-template-columns: 1fr;
            }

            .card {
                padding: 20px;
            }

            h1 {
                font-size: 28px;
            }
        }
    </style>
</head>
<body>
    <div class="shell">
        <section class="card intro">
            <div>
                <h1>体重记录</h1>
                <p class="subtitle">支持登录、多用户、体重趋势、BMI 和目标进度。</p>
                <p class="helper">登录后进入个人数据页。每个账号的数据独立保存。</p>
            </div>
            <ul class="feature-list">
                <li>记录每日体重和备注</li>
                <li>查看趋势、BMI 和目标进度</li>
                <li>批量导入历史数据</li>
            </ul>
        </section>
        <section class="card">
            {% if message %}
            <div class="message">{{ message }}</div>
            {% endif %}
            <h2 class="form-title">登录</h2>
            <form method="post" action="{{ url_for('login') }}">
                <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                <label>
                    用户名
                    <input name="username" maxlength="32" required>
                </label>
                <label>
                    密码
                    <span class="password-field">
                        <input type="password" name="password" minlength="6" required>
                        <button class="password-toggle" type="button" aria-label="显示密码" aria-pressed="false">显示</button>
                    </span>
                </label>
                <button type="submit">登录</button>
            </form>
            <p class="helper">同一设备登录后，30 天内再次访问默认无需重新输入密码。</p>
            {% if registration_enabled %}
            <h2 class="form-title">注册</h2>
            <form method="post" action="{{ url_for('register') }}">
                <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                <label>
                    用户名
                    <input name="username" maxlength="32" required>
                </label>
                <label>
                    密码
                    <span class="password-field">
                        <input type="password" name="password" minlength="6" required>
                        <button class="password-toggle" type="button" aria-label="显示密码" aria-pressed="false">显示</button>
                    </span>
                </label>
                <label>
                    邀请码
                    <input name="invite_code" required>
                </label>
                <button type="submit">创建账号</button>
            </form>
            {% else %}
            <p class="helper muted-note">当前未开放注册。</p>
            {% endif %}
        </section>
    </div>
</body>
<script>
    (() => {
        document.querySelectorAll(".password-toggle").forEach((toggle) => {
            toggle.addEventListener("click", () => {
                const input = toggle.parentElement.querySelector("input");
                const shouldShow = input.type === "password";

                input.type = shouldShow ? "text" : "password";
                toggle.textContent = shouldShow ? "隐藏" : "显示";
                toggle.setAttribute("aria-label", shouldShow ? "隐藏密码" : "显示密码");
                toggle.setAttribute("aria-pressed", String(shouldShow));
            });
        });
    })();
</script>
</html>
"""

INVITE_TEMPLATE = """
<!doctype html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>账号管理</title>
    <style>
        :root {
            color-scheme: light;
            --bg: #eef3f7;
            --card: #ffffff;
            --primary: #0f766e;
            --primary-hover: #0b5f59;
            --primary-soft: #d9f3ef;
            --muted: #5f6f6c;
            --border: #d6e0e5;
            --text: #12201c;
            --shadow: 0 18px 40px rgba(18, 32, 28, 0.08);
            --danger: #b42318;
        }

        * { box-sizing: border-box; }

        body {
            margin: 0;
            min-height: 100vh;
            display: flex;
            justify-content: center;
            padding: 24px;
            background: var(--bg);
            color: var(--text);
            font-family: "Inter", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
            line-height: 1.5;
            -webkit-text-size-adjust: 100%;
        }

        .card {
            width: min(1120px, 100%);
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: 14px;
            padding: 28px;
            box-shadow: var(--shadow);
        }

        h1 {
            margin: 0 0 12px;
            font-size: 28px;
            line-height: 1.2;
        }

        h2 {
            margin: 0 0 12px;
            font-size: 20px;
            line-height: 1.2;
        }

        p {
            margin: 0 0 16px;
            color: var(--muted);
        }

        .grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 16px;
            margin-top: 18px;
        }

        .panel {
            min-width: 0;
            padding: 18px;
            border: 1px solid var(--border);
            border-radius: 12px;
            background: #f8fafc;
        }

        label {
            display: block;
            margin-bottom: 14px;
            color: var(--muted);
            font-size: 14px;
            font-weight: 700;
        }

        input, button, select {
            width: 100%;
            min-height: 48px;
            margin-top: 6px;
            border-radius: 12px;
            padding: 12px 14px;
            font: inherit;
            font-size: 16px;
        }

        input, select {
            border: 1px solid var(--border);
            color: var(--text);
            outline: none;
        }

        input:focus {
            border-color: var(--primary);
            box-shadow: 0 0 0 3px rgba(15, 118, 110, 0.14);
        }

        button {
            border: none;
            background: var(--primary);
            color: #fff;
            font-weight: 700;
            cursor: pointer;
            touch-action: manipulation;
        }

        button:hover {
            background: var(--primary-hover);
        }

        .message {
            margin-bottom: 16px;
            padding: 12px 14px;
            background: #fff7ed;
            border: 1px solid #fed7aa;
            border-radius: 8px;
            color: #9a3412;
        }

        .success {
            background: #ecfdf3;
            border-color: #bbf7d0;
            color: #166534;
        }

        .code-box {
            display: grid;
            gap: 8px;
            margin: 18px 0;
            padding: 16px;
            border: 1px solid var(--border);
            border-left: 4px solid var(--primary);
            border-radius: 8px;
            background: #f8fafc;
        }

        .code-value {
            overflow-wrap: anywhere;
            font-size: 24px;
            font-weight: 800;
            color: var(--primary);
        }

        .actions {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
            margin-top: 18px;
        }

        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 10px;
            overflow-wrap: anywhere;
            font-size: 14px;
        }

        .table-scroll {
            width: 100%;
            overflow-x: auto;
            -webkit-overflow-scrolling: touch;
        }

        th, td {
            padding: 10px 8px;
            border-bottom: 1px solid var(--border);
            text-align: left;
            vertical-align: top;
        }

        th {
            color: var(--muted);
            font-size: 13px;
        }

        .inline-form {
            display: grid;
            gap: 8px;
        }

        .inline-form input {
            margin-top: 0;
        }

        .muted {
            color: var(--muted);
        }

        .danger-button {
            background: var(--danger);
        }

        .danger-button:hover {
            background: #8f1d14;
        }

        .action-link {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            min-height: 48px;
            padding: 0 14px;
            border-radius: 12px;
            text-decoration: none;
            color: var(--primary);
            border: 1px solid var(--primary);
            font-weight: 700;
            touch-action: manipulation;
        }

        .action-link:hover {
            background: var(--primary-soft);
        }

        @media (max-width: 800px) {
            body {
                padding: 12px;
            }

            .card {
                padding: 18px;
            }

            .grid {
                grid-template-columns: 1fr;
            }

            .actions {
                display: grid;
                grid-template-columns: 1fr;
            }
        }

        @media (max-width: 560px) {
            table,
            thead,
            tbody,
            tr,
            th,
            td {
                display: block;
            }

            thead {
                display: none;
            }

            tbody {
                display: grid;
                gap: 12px;
            }

            tr {
                border: 1px solid var(--border);
                border-radius: 12px;
                padding: 12px;
                background: #ffffff;
            }

            td {
                display: grid;
                grid-template-columns: 78px minmax(0, 1fr);
                gap: 10px;
                padding: 8px 0;
                border-bottom: 1px solid #e6edf1;
            }

            td:last-child {
                border-bottom: none;
                padding-bottom: 0;
            }

            td::before {
                content: attr(data-label);
                color: var(--muted);
                font-size: 12px;
                font-weight: 700;
            }
        }
    </style>
</head>
<body>
    <main class="card">
        <h1>账号管理</h1>
        <p>生成一次性邀请码，查看账号，并修改账号密码。</p>

        {% if message %}
        <div class="message {% if success %}success{% endif %}">{{ message }}</div>
        {% endif %}

        {% if invite_code %}
        <div class="code-box">
            <span>新邀请码</span>
            <div class="code-value">{{ invite_code }}</div>
            <p>把这个邀请码发给需要注册的用户，对方在登录页的注册表单中输入即可。</p>
        </div>
        {% endif %}

        {% if not admin_authorized %}
        <section class="panel">
            <h2>验证管理权限</h2>
            <form method="post" action="{{ url_for('admin_authorize_route') }}">
                <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                <label>
                    管理账号
                    <input name="admin_username" value="{{ admin_username_value }}" autocomplete="username" required>
                </label>
                <label>
                    管理密码
                    <input name="admin_password" type="password" autocomplete="current-password" required>
                </label>
                <button type="submit">进入管理</button>
            </form>
        </section>
        {% else %}
        <div class="grid">
            <section class="panel">
                <h2>邀请码</h2>
                <p>生成的邀请码只能注册一个账号，注册成功后自动失效。</p>
                <form method="post" action="{{ url_for('create_invite_code_route') }}">
                    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                    {% if admin_key_required %}
                    <input type="hidden" name="admin_key" value="{{ admin_key_value }}">
                    {% endif %}
                    <button type="submit">生成一个邀请码</button>
                </form>

                {% if invite_rows %}
                <div class="table-scroll">
                    <table>
                        <thead>
                            <tr>
                                <th>邀请码</th>
                                <th>状态</th>
                                <th>使用者</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for row in invite_rows %}
                            <tr>
                                <td data-label="邀请码">{{ row.code }}</td>
                                <td data-label="状态">{% if row.used_at %}已使用{% else %}未使用{% endif %}</td>
                                <td data-label="使用者">{{ row.used_by or "-" }}</td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
                {% else %}
                <p>还没有邀请码。</p>
                {% endif %}
            </section>

            <section class="panel">
                <h2>所有账号密码</h2>
                <p>把所有账号统一改成一个新密码。</p>
                <form method="post" action="{{ url_for('set_all_user_passwords_route') }}">
                    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                    {% if admin_key_required %}
                    <input type="hidden" name="admin_key" value="{{ admin_key_value }}">
                    {% endif %}
                    <label>
                        新密码
                        <input name="password" type="password" minlength="6" required>
                    </label>
                    <button class="danger-button" type="submit">修改所有账号密码</button>
                </form>
            </section>

            <section class="panel">
                <h2>管理账号密码</h2>
                <p>修改当前管理登录密码。下次进入管理页时使用新密码。</p>
                <form method="post" action="{{ url_for('set_admin_password_route') }}">
                    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                    {% if admin_key_required %}
                    <input type="hidden" name="admin_key" value="{{ admin_key_value }}">
                    {% endif %}
                    <label>
                        当前管理密码
                        <input name="current_password" type="password" autocomplete="current-password" required>
                    </label>
                    <label>
                        新管理密码
                        <input name="new_password" type="password" minlength="6" autocomplete="new-password" required>
                    </label>
                    <label>
                        确认新管理密码
                        <input name="confirm_password" type="password" minlength="6" autocomplete="new-password" required>
                    </label>
                    <button type="submit">修改管理密码</button>
                </form>
            </section>
        </div>

        <section class="panel" style="margin-top: 16px;">
            <h2>账号列表</h2>
            {% if user_rows %}
            <div class="table-scroll">
                <table>
                    <thead>
                        <tr>
                            <th>ID</th>
                            <th>用户名</th>
                            <th>注册时间</th>
                            <th>体重记录</th>
                            <th>修改密码</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for user in user_rows %}
                        <tr>
                            <td data-label="ID">{{ user.id }}</td>
                            <td data-label="用户名">{{ user.username }}</td>
                            <td data-label="注册时间">{{ user.created_at }}</td>
                            <td data-label="体重记录">{{ user.record_count }}</td>
                            <td data-label="修改密码">
                                <form class="inline-form" method="post" action="{{ url_for('set_user_password_route', user_id=user.id) }}">
                                    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                                    {% if admin_key_required %}
                                    <input type="hidden" name="admin_key" value="{{ admin_key_value }}">
                                    {% endif %}
                                    <input name="password" type="password" minlength="6" placeholder="新密码" required>
                                    <button type="submit">保存</button>
                                </form>
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
            {% else %}
            <p>还没有账号。</p>
            {% endif %}
        </section>
        {% endif %}

        <div class="actions">
            <a class="action-link" href="{{ url_for('auth_page') }}">返回登录页</a>
            {% if current_user_id %}
            <a class="action-link" href="{{ url_for('index') }}">返回记录页</a>
            {% endif %}
        </div>
    </main>
</body>
</html>
"""

PAGE_TEMPLATE = """
<!doctype html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>体重记录</title>
    <style>
        :root {
            color-scheme: light;
            --bg: #eef3f7;
            --card: #ffffff;
            --primary: #0f766e;
            --primary-hover: #0b5f59;
            --primary-soft: #d9f3ef;
            --text: #12201c;
            --muted: #5f6f6c;
            --danger: #b42318;
            --danger-soft: #fee4e2;
            --border: #d6e0e5;
            --accent: #f97316;
            --surface: #f8fafc;
            --shadow: 0 16px 36px rgba(18, 32, 28, 0.08);
        }

        * { box-sizing: border-box; }

        body {
            margin: 0;
            min-height: 100vh;
            font-family: "Inter", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
            background: var(--bg);
            color: var(--text);
            line-height: 1.5;
            -webkit-text-size-adjust: 100%;
        }

        .container {
            width: min(1180px, calc(100vw - 24px));
            margin: 24px auto;
        }

        .hero {
            display: flex;
            justify-content: space-between;
            gap: 20px;
            margin-bottom: 18px;
            align-items: flex-end;
        }

        h1, h2, h3 {
            margin: 0 0 12px;
            line-height: 1.2;
        }

        h1 {
            font-size: 34px;
        }

        h2 {
            font-size: 20px;
        }

        .subtitle {
            color: var(--muted);
            margin: 0;
            max-width: 720px;
        }

        .hero-actions {
            display: flex;
            gap: 10px;
            align-items: center;
            flex-wrap: wrap;
        }

        .layout {
            display: grid;
            grid-template-columns: minmax(300px, 360px) 1fr;
            gap: 16px;
            align-items: start;
        }

        .sidebar, .main {
            display: grid;
            gap: 16px;
        }

        .card {
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: 14px;
            padding: 22px;
            box-shadow: var(--shadow);
        }

        .sidebar > .card,
        .main > .card {
            height: 100%;
        }

        .stats {
            display: grid;
            grid-template-columns: repeat(5, 1fr);
            gap: 10px;
            margin-bottom: 18px;
            align-items: stretch;
        }

        .stat {
            display: flex;
            flex-direction: column;
            position: relative;
            overflow: hidden;
            background: linear-gradient(180deg, #ffffff 0%, #f7fbfd 100%);
            border: 1px solid var(--border);
            border-left: none;
            border-radius: 16px;
            padding: 16px;
            min-height: 124px;
            height: 100%;
            box-shadow: 0 10px 24px rgba(18, 32, 28, 0.06);
        }

        .stat::before {
            content: "";
            position: absolute;
            inset: 0 auto 0 0;
            width: 4px;
            background: linear-gradient(180deg, var(--accent) 0%, var(--primary) 100%);
        }

        .stat::after {
            content: "";
            position: absolute;
            top: -28px;
            right: -18px;
            width: 82px;
            height: 82px;
            border-radius: 50%;
            background: radial-gradient(circle, rgba(15, 118, 110, 0.1) 0%, rgba(15, 118, 110, 0) 72%);
            pointer-events: none;
        }

        .stat-label {
            color: var(--muted);
            font-size: 12px;
            letter-spacing: 0.04em;
            margin-bottom: 10px;
        }

        .stat-value {
            font-size: clamp(24px, 4vw, 30px);
            font-weight: 700;
            line-height: 1.15;
            overflow-wrap: anywhere;
            letter-spacing: -0.03em;
        }

        .stat-tip {
            font-size: 12px;
            color: var(--muted);
            margin-top: 8px;
        }

        .stat .bmi-badge {
            margin-top: auto;
            align-self: flex-start;
        }

        label {
            display: block;
            margin-bottom: 14px;
            font-size: 14px;
            color: var(--muted);
            font-weight: 700;
        }

        input, textarea, button {
            width: 100%;
            min-height: 48px;
            border-radius: 12px;
            border: 1px solid var(--border);
            padding: 12px 14px;
            font: inherit;
            font-size: 16px;
        }

        input, textarea {
            margin-top: 6px;
            background: #fff;
            color: var(--text);
            outline: none;
            transition: border-color 140ms ease, box-shadow 140ms ease;
        }

        input:focus,
        textarea:focus {
            border-color: var(--primary);
            box-shadow: 0 0 0 3px rgba(15, 118, 110, 0.14);
        }

        textarea {
            min-height: 96px;
            resize: vertical;
            line-height: 1.5;
        }

        button {
            border: none;
            background: var(--primary);
            color: white;
            font-weight: 700;
            cursor: pointer;
            transition: background 140ms ease, transform 140ms ease;
            touch-action: manipulation;
        }

        button:hover {
            background: var(--primary-hover);
        }

        button:active {
            transform: translateY(1px);
        }

        .delete-btn {
            background: var(--danger-soft);
            color: var(--danger);
            border: 1px solid #fecdca;
        }

        .delete-btn:hover {
            background: #fecdca;
        }

        .row-actions {
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
        }

        .row-actions form,
        .row-actions a,
        .hero-actions a {
            margin: 0;
        }

        .action-link {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            min-height: 48px;
            padding: 0 14px;
            border-radius: 12px;
            text-decoration: none;
            color: var(--primary);
            border: 1px solid var(--primary);
            background: transparent;
            font-weight: 700;
            transition: background 140ms ease, color 140ms ease;
            white-space: nowrap;
            touch-action: manipulation;
        }

        .action-link:hover {
            background: var(--primary-soft);
        }

        .message {
            background: #fff7ed;
            border: 1px solid #fed7aa;
            color: #9a3412;
            padding: 12px 14px;
            border-radius: 8px;
            margin-bottom: 16px;
        }

        .chart-wrap {
            position: relative;
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 12px;
            overflow-x: auto;
            overflow-y: hidden;
            -webkit-overflow-scrolling: touch;
        }

        .chart-frame {
            min-width: 640px;
        }

        .chart-tooltip {
            position: absolute;
            left: 0;
            top: 0;
            transform: translate(-50%, calc(-100% - 12px));
            max-width: 220px;
            padding: 8px 10px;
            border-radius: 8px;
            background: rgba(18, 32, 28, 0.94);
            color: #fff;
            font-size: 12px;
            line-height: 1.45;
            pointer-events: none;
            opacity: 0;
            transition: opacity 120ms ease;
            box-shadow: 0 10px 24px rgba(18, 32, 28, 0.18);
            z-index: 5;
            white-space: normal;
        }

        .chart-tooltip.visible {
            opacity: 1;
        }

        .chart-point {
            cursor: pointer;
        }

        .chart-caption {
            color: var(--muted);
            font-size: 13px;
            margin-top: 10px;
        }

        .chart-grid {
            display: grid;
            gap: 20px;
        }

        .segmented {
            display: inline-flex;
            gap: 4px;
            padding: 4px;
            border-radius: 12px;
            background: #e8eef2;
            border: 1px solid var(--border);
            margin-bottom: 14px;
            max-width: 100%;
        }

        .segmented a {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            min-height: 44px;
            padding: 8px 14px;
            border-radius: 10px;
            text-decoration: none;
            color: var(--muted);
            font-size: 14px;
            font-weight: 700;
            text-align: center;
        }

        .segmented a.active {
            background: var(--primary);
            color: #fff;
        }

        .filter-form {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 12px;
            align-items: end;
            margin-bottom: 16px;
        }

        .filter-actions {
            display: flex;
            gap: 8px;
        }

        .form-secondary {
            margin-top: 10px;
        }

        .progress-shell {
            margin-top: 12px;
            background: #e2e8f0;
            border-radius: 999px;
            height: 16px;
            overflow: hidden;
        }

        .progress-fill {
            height: 100%;
            border-radius: 999px;
            background: linear-gradient(90deg, var(--accent) 0%, var(--primary) 100%);
        }

        .progress-meta {
            display: flex;
            justify-content: space-between;
            gap: 12px;
            margin-top: 10px;
            font-size: 13px;
            color: var(--muted);
        }

        .table-scroll {
            width: 100%;
            overflow-x: auto;
            -webkit-overflow-scrolling: touch;
        }

        table {
            width: 100%;
            border-collapse: collapse;
            min-width: 680px;
        }

        th, td {
            text-align: left;
            padding: 12px 8px;
            border-bottom: 1px solid var(--border);
            vertical-align: top;
        }

        th {
            color: var(--muted);
            font-weight: 600;
            font-size: 14px;
        }

        .empty {
            color: var(--muted);
            padding: 24px 0 8px;
        }

        .row-note {
            color: var(--muted);
            font-size: 13px;
            white-space: pre-wrap;
            word-break: break-word;
        }

        .helper {
            color: var(--muted);
            font-size: 13px;
            margin-top: -6px;
            margin-bottom: 14px;
        }

        .bmi-badge {
            display: inline-block;
            margin-top: 8px;
            padding: 6px 10px;
            border-radius: 999px;
            background: var(--primary-soft);
            color: #0b5f59;
            font-size: 12px;
            font-weight: 700;
        }

        @media (max-width: 860px) {
            .container {
                margin: 20px auto;
            }

            .hero, .layout {
                grid-template-columns: 1fr;
                display: grid;
                align-items: start;
            }

            .stats {
                grid-template-columns: repeat(2, 1fr);
                gap: 12px;
            }

            .filter-form {
                grid-template-columns: 1fr;
            }

            .filter-actions {
                align-items: stretch;
            }

            .chart-frame {
                min-width: 580px;
            }
        }

        @media (max-width: 560px) {
            .container {
                width: calc(100vw - 16px);
                margin: 8px auto 16px;
            }

            .hero {
                gap: 12px;
            }

            h1 {
                font-size: 28px;
            }

            .stats {
                grid-template-columns: 1fr;
                gap: 10px;
            }

            .stat {
                min-height: 0;
                padding: 14px 16px;
            }

            .stat-label {
                margin-bottom: 8px;
                font-size: 11px;
            }

            .stat-value {
                font-size: clamp(28px, 8vw, 34px);
            }

            .stat-tip {
                font-size: 13px;
            }

            .stat .bmi-badge {
                margin-top: 10px;
            }

            .card {
                padding: 16px;
            }

            .segmented,
            .filter-actions,
            .row-actions {
                width: 100%;
            }

            .segmented {
                display: grid;
                grid-template-columns: repeat(3, minmax(0, 1fr));
            }

            .segmented a,
            .filter-actions > *,
            .row-actions > * {
                flex: 1 1 0;
            }

            .filter-actions,
            .row-actions {
                display: grid;
                grid-template-columns: 1fr;
            }

            .chart-wrap {
                padding: 10px;
            }

            .chart-frame {
                min-width: 520px;
            }

            table,
            thead,
            tbody,
            tr,
            th,
            td {
                display: block;
            }

            table {
                min-width: 0;
            }

            thead {
                display: none;
            }

            tbody {
                display: grid;
                gap: 12px;
            }

            tr {
                border: 1px solid var(--border);
                border-radius: 12px;
                padding: 12px;
                background: var(--surface);
            }

            td {
                display: grid;
                grid-template-columns: 76px minmax(0, 1fr);
                gap: 10px;
                padding: 8px 0;
                border-bottom: 1px solid #e6edf1;
            }

            td:last-child {
                border-bottom: none;
                padding-bottom: 0;
            }

            td::before {
                content: attr(data-label);
                color: var(--muted);
                font-size: 12px;
                font-weight: 700;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="hero">
            <div>
                <h1>体重记录</h1>
                <p class="subtitle">当前用户：{{ current_username }}。支持登录、批量导入、趋势图、BMI 和目标进度。</p>
            </div>
            <div class="hero-actions">
                <a class="action-link" href="{{ url_for('logout') }}">退出登录</a>
            </div>
        </div>

        {% if message %}
        <div class="message">{{ message }}</div>
        {% endif %}

        <div class="stats">
            <div class="stat">
                <div class="stat-label">最新体重</div>
                <div class="stat-value">{{ latest_weight if latest_weight is not none else "--" }}</div>
                <div class="stat-tip">{% if latest_weight is not none %}kg{% else %}暂无数据{% endif %}</div>
            </div>
            <div class="stat">
                <div class="stat-label">记录总数</div>
                <div class="stat-value">{{ total_count }}</div>
                <div class="stat-tip">筛选范围内记录数</div>
            </div>
            <div class="stat">
                <div class="stat-label">平均体重</div>
                <div class="stat-value">{{ average_weight if average_weight is not none else "--" }}</div>
                <div class="stat-tip">{% if average_weight is not none %}kg{% else %}暂无数据{% endif %}</div>
            </div>
            <div class="stat">
                <div class="stat-label">当前 BMI</div>
                <div class="stat-value">{{ bmi_value if bmi_value is not none else "--" }}</div>
                <div class="stat-tip">{% if height_cm %}身高 {{ height_cm }} cm{% else %}先填写身高{% endif %}</div>
                {% if bmi_category %}
                <div class="bmi-badge">{{ bmi_category }}</div>
                {% endif %}
            </div>
            <div class="stat">
                <div class="stat-label">距目标体重</div>
                <div class="stat-value">{{ remaining_delta if remaining_delta is not none else "--" }}</div>
                <div class="stat-tip">{% if target_weight %}目标 {{ target_weight }} kg{% else %}先设置目标{% endif %}</div>
                {% if remaining_status %}
                <div class="bmi-badge">{{ remaining_status }}</div>
                {% endif %}
            </div>
        </div>

        <div class="layout">
            <aside class="sidebar">
                <section class="card">
                    <h2>{{ "编辑记录" if editing_record else "新增记录" }}</h2>
                    <form method="post" action="{{ url_for('update_record', record_id=editing_record['id'], chart=chart_mode, start_date=start_date, end_date=end_date) if editing_record else url_for('add_record', chart=chart_mode, start_date=start_date, end_date=end_date) }}">
                        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                        <label>
                            日期
                            <input type="date" name="record_date" value="{{ form_record_date }}" required>
                        </label>
                        <label>
                            体重（kg）
                            <input type="number" name="weight" step="0.1" min="1" value="{{ form_weight }}" placeholder="例如 60.5" required>
                        </label>
                        <label>
                            备注
                            <textarea name="note" placeholder="例如：晨起空腹、运动后等">{{ form_note }}</textarea>
                        </label>
                        <button type="submit">{{ "保存修改" if editing_record else "保存记录" }}</button>
                    </form>
                    {% if editing_record %}
                    <div class="form-secondary">
                        <a class="action-link" href="{{ url_for('index', chart=chart_mode, start_date=start_date, end_date=end_date) }}">取消编辑</a>
                    </div>
                    {% endif %}
                </section>

                <section class="card">
                    <h2>批量添加</h2>
                    <p class="helper">每行一条，支持多种格式，例如：`2026-04-06,59.8,晨起`、`2026-04-06 59.8 晨起`、`2026/04/06 59.8`、`2026-04-06，59.8，晨起`。</p>
                    <form method="post" action="{{ url_for('bulk_add_records', chart=chart_mode, start_date=start_date, end_date=end_date) }}">
                        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                        <label>
                            批量数据
                            <textarea name="bulk_text" placeholder="2026-04-01,60.5,晨起&#10;2026-04-02 60.2&#10;2026/04/03，59.9，运动后"></textarea>
                        </label>
                        <button type="submit">批量保存</button>
                    </form>
                </section>

                <section class="card">
                    <h2>身体数据设置</h2>
                    <p class="helper">BMI = 体重(kg) / 身高(m)^2。目标体重会用于差值、进度和图表提醒线。</p>
                    <form method="post" action="{{ url_for('save_profile', chart=chart_mode, start_date=start_date, end_date=end_date) }}">
                        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                        <label>
                            身高（cm）
                            <input type="number" name="height_cm" step="0.1" min="50" value="{{ height_cm or '' }}" placeholder="例如 170">
                        </label>
                        <label>
                            目标体重（kg）
                            <input type="number" name="target_weight" step="0.1" min="1" value="{{ target_weight or '' }}" placeholder="例如 55">
                        </label>
                        <button type="submit">保存设置</button>
                    </form>
                </section>

                <section class="card">
                    <h2>目标达成示意</h2>
                    {% if progress_percent is not none %}
                    <div class="stat-value">{{ progress_percent }}%</div>
                    <div class="progress-shell">
                        <div class="progress-fill" style="width: {{ progress_percent }}%;"></div>
                    </div>
                    <div class="progress-meta">
                        <span>起始 {{ start_weight_for_goal }} kg</span>
                        <span>当前 {{ latest_weight }} kg</span>
                        <span>目标 {{ target_weight }} kg</span>
                    </div>
                    {% else %}
                    <div class="empty">设置目标体重后，会按筛选范围内的第一条记录作为起点计算进度。</div>
                    {% endif %}
                </section>
            </aside>

            <main class="main">
                <section class="card">
                    <h2>体重变化趋势</h2>
                    <form class="filter-form" method="get" action="{{ url_for('index') }}">
                        <label>
                            开始日期
                            <input type="date" name="start_date" value="{{ start_date }}">
                        </label>
                        <label>
                            结束日期
                            <input type="date" name="end_date" value="{{ end_date }}">
                        </label>
                        <div class="filter-actions">
                            <input type="hidden" name="chart" value="{{ chart_mode }}">
                            <button type="submit">筛选</button>
                            <a class="action-link" href="{{ url_for('index', chart=chart_mode) }}">清空</a>
                        </div>
                    </form>
                    <div class="segmented">
                        <a href="{{ url_for('index', chart='daily', start_date=start_date, end_date=end_date) }}" class="{{ 'active' if chart_mode == 'daily' else '' }}">按日</a>
                        <a href="{{ url_for('index', chart='weekly', start_date=start_date, end_date=end_date) }}" class="{{ 'active' if chart_mode == 'weekly' else '' }}">按周</a>
                        <a href="{{ url_for('index', chart='monthly', start_date=start_date, end_date=end_date) }}" class="{{ 'active' if chart_mode == 'monthly' else '' }}">按月</a>
                    </div>
                    <div class="chart-grid">
                        {% if chart_svg %}
                        <div>
                            <div class="chart-wrap"><div class="chart-frame">{{ chart_svg|safe }}</div></div>
                            <div class="chart-caption">{{ chart_caption }}</div>
                        </div>
                        {% else %}
                        <div class="empty">至少需要两条记录，趋势图才更有意义。</div>
                        {% endif %}

                        {% if dual_chart_svg %}
                        <div>
                            <div class="chart-wrap"><div class="chart-frame">{{ dual_chart_svg|safe }}</div></div>
                            <div class="chart-caption">体重与 BMI 双曲线联动查看，左轴为体重，右轴为 BMI。</div>
                        </div>
                        {% elif height_cm %}
                        <div class="empty">需要至少两条带 BMI 的记录，才能绘制双曲线图。</div>
                        {% else %}
                        <div class="empty">先填写身高，才能绘制 BMI 曲线。</div>
                        {% endif %}
                    </div>
                </section>

                <section class="card">
                    <h2>历史记录</h2>
                    {% if records %}
                    <div class="table-scroll">
                        <table>
                            <thead>
                                <tr>
                                    <th>日期</th>
                                    <th>体重</th>
                                    <th>BMI</th>
                                    <th>备注</th>
                                    <th>操作</th>
                                </tr>
                            </thead>
                            <tbody>
                                {% for record in records %}
                                <tr>
                                    <td data-label="日期">{{ record["record_date"] }}</td>
                                    <td data-label="体重">{{ "%.1f"|format(record["weight"]) }} kg</td>
                                    <td data-label="BMI">{% if record["bmi"] is not none %}{{ "%.1f"|format(record["bmi"]) }}{% else %}-{% endif %}</td>
                                    <td data-label="备注">{% if record["note"] %}<div class="row-note">{{ record["note"] }}</div>{% else %}<span class="row-note">-</span>{% endif %}</td>
                                    <td data-label="操作">
                                        <div class="row-actions">
                                            <a class="action-link" href="{{ url_for('index', edit=record['id'], chart=chart_mode, start_date=start_date, end_date=end_date) }}">编辑</a>
                                            <form method="post" action="{{ url_for('delete_record', record_id=record['id'], chart=chart_mode, start_date=start_date, end_date=end_date) }}">
                                                <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                                                <button class="delete-btn" type="submit">删除</button>
                                            </form>
                                        </div>
                                    </td>
                                </tr>
                                {% endfor %}
                            </tbody>
                        </table>
                    </div>
                    {% else %}
                    <div class="empty">还没有记录，先添加今天的体重。</div>
                    {% endif %}
                </section>
            </main>
        </div>
    </div>
</body>
<script>
    (() => {
        const chartWraps = document.querySelectorAll(".chart-wrap");

        chartWraps.forEach((wrap) => {
            const tooltip = document.createElement("div");
            tooltip.className = "chart-tooltip";
            wrap.appendChild(tooltip);

            const showTooltip = (event) => {
                const point = event.target.closest(".chart-point");
                if (!point) {
                    tooltip.classList.remove("visible");
                    return;
                }

                tooltip.textContent = point.dataset.tooltip || "";
                tooltip.classList.add("visible");

                const rect = wrap.getBoundingClientRect();
                const offsetX = event.clientX - rect.left;
                const offsetY = event.clientY - rect.top;
                tooltip.style.left = `${offsetX}px`;
                tooltip.style.top = `${offsetY}px`;
            };

            wrap.addEventListener("pointermove", showTooltip);
            wrap.addEventListener("click", showTooltip);

            wrap.addEventListener("mouseleave", () => {
                tooltip.classList.remove("visible");
            });

            wrap.addEventListener("pointerleave", () => {
                tooltip.classList.remove("visible");
            });
        });

        document.addEventListener("click", (event) => {
            if (event.target.closest(".chart-wrap")) {
                return;
            }
            document.querySelectorAll(".chart-tooltip").forEach((tooltip) => {
                tooltip.classList.remove("visible");
            });
        });
    })();
</script>
</html>
"""


def generate_csrf_token() -> str:
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


app.jinja_env.globals["csrf_token"] = generate_csrf_token


@app.before_request
def protect_post_requests() -> None:
    if not app.config["CSRF_ENABLED"] or request.method in {"GET", "HEAD", "OPTIONS"}:
        return

    expected_token = session.get("csrf_token")
    submitted_token = request.form.get("csrf_token", "")
    if not expected_token or not secrets.compare_digest(expected_token, submitted_token):
        abort(400, "Invalid CSRF token.")


def is_rate_limited(scope: str, identity: str) -> bool:
    attempts = int(app.config["RATE_LIMIT_ATTEMPTS"])
    window_seconds = int(app.config["RATE_LIMIT_WINDOW_SECONDS"])
    now = time.monotonic()
    key = f"{scope}:{identity}"
    recent_attempts = [item for item in RATE_LIMITS.get(key, []) if now - item < window_seconds]
    if len(recent_attempts) >= attempts:
        RATE_LIMITS[key] = recent_attempts
        return True
    recent_attempts.append(now)
    RATE_LIMITS[key] = recent_attempts
    return False


def rate_limit_identity(username: str) -> str:
    remote_addr = request.remote_addr or "unknown"
    return f"{remote_addr}:{username.lower()}"


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def build_redirect_url(
    message: str,
    edit_id: int | None = None,
    chart_mode: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> str:
    params = {"message": message}
    if edit_id is not None:
        params["edit"] = str(edit_id)
    if chart_mode:
        params["chart"] = chart_mode
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    return f"{url_for('index')}?{urlencode(params)}"


def init_db() -> None:
    with closing(get_connection()) as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id INTEGER PRIMARY KEY,
                height_cm REAL,
                target_weight REAL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS weight_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                record_date TEXT NOT NULL,
                weight REAL NOT NULL,
                note TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS invite_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                used_at TEXT,
                used_by_user_id INTEGER,
                FOREIGN KEY (used_by_user_id) REFERENCES users(id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS admin_credentials (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                username TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO admin_credentials (id, username, password_hash, updated_at)
            VALUES (1, ?, ?, ?)
            """,
            (
                app.config["ADMIN_USERNAME"],
                generate_password_hash(app.config["ADMIN_PASSWORD"]),
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        record_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(weight_records)").fetchall()
        }
        if "user_id" not in record_columns:
            connection.execute("ALTER TABLE weight_records ADD COLUMN user_id INTEGER")
        seed_code = app.config["REGISTER_INVITE_CODE"].strip()
        if seed_code:
            connection.execute(
                """
                INSERT OR IGNORE INTO invite_codes (code, created_at)
                VALUES (?, ?)
                """,
                (seed_code, datetime.now().isoformat(timespec="seconds")),
            )
        connection.commit()


def login_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("auth_page"))
        return view_func(*args, **kwargs)

    return wrapped


def get_current_user_id() -> int | None:
    return session.get("user_id")


def get_current_username() -> str:
    return session.get("username", "")


def validate_user_credentials(username: str, password: str) -> tuple[bool, str]:
    if not username or not password:
        return False, "用户名和密码不能为空。"
    if len(username) < 2 or len(username) > 32:
        return False, "用户名长度需要在 2 到 32 个字符之间。"
    if len(password) < 6:
        return False, "密码至少需要 6 位。"
    return True, ""


def insert_user(connection: sqlite3.Connection, username: str, password: str) -> tuple[bool, str, int | None]:
    exists = connection.execute(
        "SELECT id FROM users WHERE username = ?",
        (username,),
    ).fetchone()
    if exists:
        return False, "用户名已存在。", None

    connection.execute(
        """
        INSERT INTO users (username, password_hash, created_at)
        VALUES (?, ?, ?)
        """,
        (username, generate_password_hash(password), datetime.now().isoformat(timespec="seconds")),
    )
    user_id = connection.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()["id"]
    connection.execute(
        "INSERT OR IGNORE INTO user_profiles (user_id, height_cm, target_weight) VALUES (?, NULL, NULL)",
        (user_id,),
    )
    return True, "注册成功，请登录。", int(user_id)


def create_user(username: str, password: str) -> tuple[bool, str]:
    ok, message = validate_user_credentials(username, password)
    if not ok:
        return False, message

    with closing(get_connection()) as connection:
        ok, message, _ = insert_user(connection, username, password)
        connection.commit()
    return ok, message


def generate_invite_code() -> str:
    return secrets.token_urlsafe(12).replace("-", "").replace("_", "")[:16].upper()


def create_invite_code() -> str:
    with closing(get_connection()) as connection:
        for _ in range(5):
            code = generate_invite_code()
            try:
                connection.execute(
                    """
                    INSERT INTO invite_codes (code, created_at)
                    VALUES (?, ?)
                    """,
                    (code, datetime.now().isoformat(timespec="seconds")),
                )
                connection.commit()
                return code
            except sqlite3.IntegrityError:
                continue
    raise RuntimeError("Failed to generate a unique invite code.")


def create_user_with_invite_code(username: str, password: str, invite_code: str) -> tuple[bool, str]:
    ok, message = validate_user_credentials(username, password)
    if not ok:
        return False, message

    code = invite_code.strip()
    if not code:
        return False, "请输入邀请码。"

    with closing(get_connection()) as connection:
        connection.execute("BEGIN IMMEDIATE")
        invite_row = connection.execute(
            """
            SELECT id, used_at
            FROM invite_codes
            WHERE code = ?
            """,
            (code,),
        ).fetchone()
        if not invite_row or invite_row["used_at"] is not None:
            connection.rollback()
            return False, "邀请码错误或已被使用。"

        ok, message, user_id = insert_user(connection, username, password)
        if not ok or user_id is None:
            connection.rollback()
            return False, message

        connection.execute(
            """
            UPDATE invite_codes
            SET used_at = ?, used_by_user_id = ?
            WHERE id = ? AND used_at IS NULL
            """,
            (datetime.now().isoformat(timespec="seconds"), user_id, invite_row["id"]),
        )
        connection.commit()
    return True, "注册成功，请登录。"


def authenticate_user(username: str, password: str) -> tuple[bool, str]:
    with closing(get_connection()) as connection:
        row = connection.execute(
            "SELECT id, username, password_hash FROM users WHERE username = ?",
            (username,),
        ).fetchone()
    if not row or not check_password_hash(row["password_hash"], password):
        return False, "用户名或密码错误。"
    session.permanent = True
    session["user_id"] = row["id"]
    session["username"] = row["username"]
    return True, "登录成功。当前设备 30 天内再次访问无需重新输入密码。"


def parse_record_form(record_date: str, weight_raw: str) -> tuple[str, float]:
    if not record_date or not weight_raw:
        raise ValueError("日期和体重不能为空。")
    try:
        datetime.strptime(record_date, "%Y-%m-%d")
        weight = float(weight_raw)
    except ValueError as exc:
        raise ValueError("请输入合法的日期和体重。") from exc
    if weight <= 0:
        raise ValueError("体重必须大于 0。")
    return record_date, weight


def parse_filter_dates(start_date: str | None, end_date: str | None) -> tuple[str, str]:
    start_value = (start_date or "").strip()
    end_value = (end_date or "").strip()
    if start_value:
        datetime.strptime(start_value, "%Y-%m-%d")
    if end_value:
        datetime.strptime(end_value, "%Y-%m-%d")
    if start_value and end_value and start_value > end_value:
        raise ValueError("开始日期不能晚于结束日期。")
    return start_value, end_value


def parse_bulk_records(bulk_text: str) -> list[tuple[str, float, str]]:
    entries = []
    for index, raw_line in enumerate(bulk_text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue

        normalized = line.replace("，", ",").replace("\t", " ").strip()
        parts = [part.strip() for part in normalized.split(",", 2)] if "," in normalized else []

        if len(parts) >= 2:
            date_raw = parts[0].replace("/", "-")
            weight_raw = parts[1]
            note = parts[2] if len(parts) == 3 else ""
        else:
            match = re.match(
                r"^\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2})\s+([0-9]+(?:\.[0-9]+)?)\s*(.*)$",
                normalized,
            )
            if not match:
                raise ValueError(
                    f"第 {index} 行格式错误。支持 `日期,体重,备注`、`日期 体重 备注`、`日期/体重` 这类格式。"
                )
            date_raw = match.group(1).replace("/", "-")
            weight_raw = match.group(2)
            note = match.group(3).strip()

        record_date, weight = parse_record_form(date_raw, weight_raw)
        entries.append((record_date, weight, note))
    if not entries:
        raise ValueError("批量数据不能为空。")
    return entries


def get_profile(user_id: int) -> dict[str, float | None]:
    with closing(get_connection()) as connection:
        row = connection.execute(
            "SELECT height_cm, target_weight FROM user_profiles WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    if not row:
        return {"height_cm": None, "target_weight": None}
    return {
        "height_cm": round(float(row["height_cm"]), 1) if row["height_cm"] is not None else None,
        "target_weight": round(float(row["target_weight"]), 1) if row["target_weight"] is not None else None,
    }


def calculate_bmi(weight: float, height_cm: float | None) -> float | None:
    if height_cm is None or height_cm <= 0:
        return None
    height_m = height_cm / 100
    return round(weight / (height_m * height_m), 1)


def get_bmi_category(bmi: float | None) -> str | None:
    if bmi is None:
        return None
    if bmi < 18.5:
        return "偏瘦"
    if bmi < 24:
        return "正常"
    if bmi < 28:
        return "超重"
    return "肥胖"


def build_record_filters(start_date: str, end_date: str, user_id: int) -> tuple[str, list]:
    conditions = ["user_id = ?"]
    params: list = [user_id]
    if start_date:
        conditions.append("record_date >= ?")
        params.append(start_date)
    if end_date:
        conditions.append("record_date <= ?")
        params.append(end_date)
    return f"WHERE {' AND '.join(conditions)}", params


def fetch_records(user_id: int, start_date: str = "", end_date: str = "") -> list[dict]:
    profile = get_profile(user_id)
    height_cm = profile["height_cm"]
    where_clause, params = build_record_filters(start_date, end_date, user_id)
    with closing(get_connection()) as connection:
        rows = connection.execute(
            f"""
            SELECT id, record_date, weight, note
            FROM weight_records
            {where_clause}
            ORDER BY record_date DESC, id DESC
            """,
            params,
        ).fetchall()

    records = []
    for row in rows:
        weight = round(float(row["weight"]), 1)
        records.append(
            {
                "id": row["id"],
                "record_date": row["record_date"],
                "weight": weight,
                "note": row["note"] or "",
                "bmi": calculate_bmi(weight, height_cm),
            }
        )
    return records


def get_chart_mode(chart_mode: str | None) -> str:
    if chart_mode in {"daily", "weekly", "monthly"}:
        return chart_mode
    return "daily"


def aggregate_records(records: list[dict], chart_mode: str) -> list[dict]:
    if chart_mode == "daily":
        return list(reversed(records))

    grouped: OrderedDict[str, list[dict]] = OrderedDict()
    for record in reversed(records):
        record_day = datetime.strptime(record["record_date"], "%Y-%m-%d").date()
        if chart_mode == "weekly":
            year, week, _ = record_day.isocalendar()
            key = f"{year}-W{week:02d}"
            label = f"{year} 第{week}周"
        else:
            key = record_day.strftime("%Y-%m")
            label = record_day.strftime("%Y-%m")
        grouped.setdefault(key, []).append(
            {"weight": record["weight"], "bmi": record["bmi"], "label": label}
        )

    aggregated = []
    for key, values in grouped.items():
        avg_weight = round(sum(item["weight"] for item in values) / len(values), 1)
        bmi_values = [item["bmi"] for item in values if item["bmi"] is not None]
        aggregated.append(
            {
                "record_date": key,
                "label": values[-1]["label"],
                "weight": avg_weight,
                "bmi": round(sum(bmi_values) / len(bmi_values), 1) if bmi_values else None,
            }
        )
    return aggregated


def fetch_record_by_id(record_id: int, user_id: int) -> dict | None:
    with closing(get_connection()) as connection:
        row = connection.execute(
            """
            SELECT id, record_date, weight, note
            FROM weight_records
            WHERE id = ? AND user_id = ?
            """,
            (record_id, user_id),
        ).fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "record_date": row["record_date"],
        "weight": round(float(row["weight"]), 1),
        "note": row["note"] or "",
    }


def fetch_stats(user_id: int, start_date: str = "", end_date: str = "") -> tuple[float | None, int, float | None]:
    where_clause, params = build_record_filters(start_date, end_date, user_id)
    with closing(get_connection()) as connection:
        latest_row = connection.execute(
            f"""
            SELECT weight
            FROM weight_records
            {where_clause}
            ORDER BY record_date DESC, id DESC
            LIMIT 1
            """,
            params,
        ).fetchone()
        summary_row = connection.execute(
            f"""
            SELECT COUNT(*) AS total_count, AVG(weight) AS average_weight
            FROM weight_records
            {where_clause}
            """,
            params,
        ).fetchone()

    latest_weight = round(float(latest_row["weight"]), 1) if latest_row else None
    total_count = int(summary_row["total_count"]) if summary_row else 0
    average_weight = (
        round(float(summary_row["average_weight"]), 1)
        if summary_row and summary_row["average_weight"] is not None
        else None
    )
    return latest_weight, total_count, average_weight


def get_remaining_delta(latest_weight: float | None, target_weight: float | None) -> tuple[float | None, str | None]:
    if latest_weight is None or target_weight is None:
        return None, None
    delta = round(latest_weight - target_weight, 1)
    if delta > 0:
        return delta, "还需下降"
    if delta < 0:
        return abs(delta), "已低于目标"
    return 0.0, "已达目标"


def get_goal_progress(records: list[dict], target_weight: float | None) -> tuple[float | None, float | None]:
    if not records or target_weight is None:
        return None, None
    start_weight = records[-1]["weight"]
    latest_weight = records[0]["weight"]
    total_change_needed = start_weight - target_weight
    if total_change_needed <= 0:
        return (100.0 if latest_weight <= target_weight else 0.0), start_weight
    progress = ((start_weight - latest_weight) / total_change_needed) * 100
    return max(0.0, min(100.0, round(progress, 1))), start_weight


def format_x_label(record: dict, chart_mode: str) -> str:
    if chart_mode == "daily":
        try:
            return datetime.strptime(record["record_date"], "%Y-%m-%d").strftime("%m-%d")
        except ValueError:
            return record["record_date"]
    if chart_mode == "weekly":
        label = record.get("label", "")
        if "第" in label and "周" in label:
            return label.replace(" 第", " W").replace("周", "")
        return label
    return record.get("label", record["record_date"])


def build_x_axis_labels(points: list[tuple[float, float, dict]], chart_mode: str, chart_height: int) -> str:
    if not points:
        return ""

    total = len(points)
    if total <= 6:
        indices = list(range(total))
    else:
        target_ticks = 6
        step = max(1, round((total - 1) / (target_ticks - 1)))
        indices = sorted({0, total - 1, *range(0, total, step)})

    labels = []
    for index in indices:
        x, _, record = points[index]
        label = format_x_label(record, chart_mode)
        labels.append(
            f"<line x1='{x:.1f}' y1='{chart_height - 34}' x2='{x:.1f}' y2='{chart_height - 28}' stroke='#b9c6cc' />"
            f"<text x='{x:.1f}' y='{chart_height - 12}' text-anchor='middle' font-size='11' fill='#5f6f6c'>{escape(label)}</text>"
        )
    return "".join(labels)


def build_point_tooltip(record: dict) -> str:
    parts = [f"日期: {record['record_date']}", f"体重: {record['weight']:.1f} kg"]
    if record.get("bmi") is not None:
        parts.append(f"BMI: {record['bmi']:.1f}")
    return " | ".join(parts)


def build_weight_value_labels(points: list[tuple[float, float, dict]]) -> str:
    if not points:
        return ""

    total = len(points)
    if total <= 5:
        indices = list(range(total))
    else:
        weight_values = [record["weight"] for _, _, record in points]
        min_index = weight_values.index(min(weight_values))
        max_index = weight_values.index(max(weight_values))
        indices = sorted({0, total - 1, min_index, max_index})

        if total > 8:
            mid_index = total // 2
            indices = sorted({*indices, mid_index})

    labels = []
    for label_order, index in enumerate(indices):
        x, y, record = points[index]
        offset = -16 if label_order % 2 == 0 else 24
        label_y = y + offset
        rect_y = label_y - 11
        labels.append(
            f"<rect x='{x - 17:.1f}' y='{rect_y:.1f}' width='34' height='18' rx='6' fill='#ffffff' stroke='#d6e0e5' />"
            f"<text x='{x:.1f}' y='{label_y + 2:.1f}' text-anchor='middle' font-size='11' font-weight='700' fill='#0b5f59'>{record['weight']:.1f}</text>"
        )
    return "".join(labels)


def build_chart_svg(records: list[dict], chart_mode: str, target_weight: float | None) -> str:
    chart_records = aggregate_records(records, chart_mode)
    if len(chart_records) < 2:
        return ""

    width = 760
    height = 280
    left = 52
    right = 24
    top = 24
    bottom = 40
    plot_width = width - left - right
    plot_height = height - top - bottom

    weights = [record["weight"] for record in chart_records]
    if target_weight is not None:
        weights.append(target_weight)
    min_axis = min(weights) - 0.5
    max_axis = max(weights) + 0.5
    axis_range = max(max_axis - min_axis, 1.0)

    points = []
    for index, record in enumerate(chart_records):
        x = left + (plot_width * index / (len(chart_records) - 1))
        y_ratio = (record["weight"] - min_axis) / axis_range
        y = top + plot_height - (y_ratio * plot_height)
        points.append((x, y, record))
    x_axis_labels = build_x_axis_labels(points, chart_mode, height)

    y_ticks = []
    for tick in range(4):
        value = min_axis + (axis_range * tick / 3)
        y = top + plot_height - (plot_height * tick / 3)
        y_ticks.append(
            f"<line x1='{left}' y1='{y:.1f}' x2='{width - right}' y2='{y:.1f}' stroke='#d6e0e5' stroke-dasharray='4 4' />"
            f"<text x='{left - 8}' y='{y + 4:.1f}' text-anchor='end' font-size='11' fill='#5f6f6c'>{value:.1f}</text>"
        )

    goal_line = ""
    if target_weight is not None:
        goal_y = top + plot_height - (((target_weight - min_axis) / axis_range) * plot_height)
        goal_line = (
            f"<line x1='{left}' y1='{goal_y:.1f}' x2='{width - right}' y2='{goal_y:.1f}' "
            f"stroke='#b42318' stroke-width='2' stroke-dasharray='8 6' />"
            f"<text x='{width - right}' y='{goal_y - 6:.1f}' text-anchor='end' font-size='12' fill='#b42318'>"
            f"目标 {target_weight:.1f} kg</text>"
        )

    circles = []
    for x, y, record in points:
        tooltip = escape(build_point_tooltip(record), quote=True)
        circles.append(
            f"<circle class='chart-point' data-tooltip='{tooltip}' cx='{x:.1f}' cy='{y:.1f}' r='6.5' fill='#f97316' stroke='#ffffff' stroke-width='2'>"
            f"<title>{escape(build_point_tooltip(record))}</title>"
            f"</circle>"
        )
    value_labels = build_weight_value_labels(points)

    return (
        f"<svg viewBox='0 0 {width} {height}' width='100%' role='img' aria-label='体重变化趋势图'>"
        f"<rect x='0' y='0' width='{width}' height='{height}' rx='8' fill='#ffffff' />"
        f"{''.join(y_ticks)}{goal_line}"
        f"<polyline fill='none' stroke='#0f766e' stroke-width='3' points='{' '.join(f'{x:.1f},{y:.1f}' for x, y, _ in points)}' />"
        f"{value_labels}{''.join(circles)}{x_axis_labels}"
        f"</svg>"
    )


def build_dual_chart_svg(records: list[dict], chart_mode: str, target_weight: float | None) -> str:
    chart_records = aggregate_records(records, chart_mode)
    if len(chart_records) < 2 or any(record.get("bmi") is None for record in chart_records):
        return ""

    width = 760
    height = 300
    left = 54
    right = 54
    top = 24
    bottom = 42
    plot_width = width - left - right
    plot_height = height - top - bottom

    weights = [record["weight"] for record in chart_records]
    bmis = [record["bmi"] for record in chart_records]
    if target_weight is not None:
        weights.append(target_weight)
    min_weight = min(weights) - 0.5
    max_weight = max(weights) + 0.5
    min_bmi = min(bmis) - 0.5
    max_bmi = max(bmis) + 0.5
    weight_range = max(max_weight - min_weight, 1.0)
    bmi_range = max(max_bmi - min_bmi, 1.0)

    weight_points = []
    bmi_points = []
    point_markers = []
    for index, record in enumerate(chart_records):
        x = left + (plot_width * index / (len(chart_records) - 1))
        wy = top + plot_height - (((record["weight"] - min_weight) / weight_range) * plot_height)
        by = top + plot_height - (((record["bmi"] - min_bmi) / bmi_range) * plot_height)
        weight_points.append(f"{x:.1f},{wy:.1f}")
        bmi_points.append(f"{x:.1f},{by:.1f}")
        tooltip = escape(build_point_tooltip(record))
        point_markers.append(
            f"<circle class='chart-point' data-tooltip='{escape(build_point_tooltip(record), quote=True)}' cx='{x:.1f}' cy='{wy:.1f}' r='5.5' fill='#0f766e' stroke='#ffffff' stroke-width='1.5'>"
            f"<title>{tooltip}</title>"
            f"</circle>"
            f"<circle class='chart-point' data-tooltip='{escape(build_point_tooltip(record), quote=True)}' cx='{x:.1f}' cy='{by:.1f}' r='5.5' fill='#f97316' stroke='#ffffff' stroke-width='1.5'>"
            f"<title>{tooltip}</title>"
            f"</circle>"
        )
    x_axis_labels = build_x_axis_labels(
        [(left + (plot_width * index / (len(chart_records) - 1)), 0, record) for index, record in enumerate(chart_records)],
        chart_mode,
        height,
    )

    grid_lines = []
    for tick in range(4):
        y = top + plot_height - (plot_height * tick / 3)
        weight_value = min_weight + (weight_range * tick / 3)
        bmi_value = min_bmi + (bmi_range * tick / 3)
        grid_lines.append(
            f"<line x1='{left}' y1='{y:.1f}' x2='{width - right}' y2='{y:.1f}' stroke='#d6e0e5' stroke-dasharray='4 4' />"
            f"<text x='{left - 8}' y='{y + 4:.1f}' text-anchor='end' font-size='11' fill='#0f766e'>{weight_value:.1f}</text>"
            f"<text x='{width - right + 8}' y='{y + 4:.1f}' text-anchor='start' font-size='11' fill='#f97316'>{bmi_value:.1f}</text>"
        )

    goal_line = ""
    if target_weight is not None:
        goal_y = top + plot_height - (((target_weight - min_weight) / weight_range) * plot_height)
        goal_line = (
            f"<line x1='{left}' y1='{goal_y:.1f}' x2='{width - right}' y2='{goal_y:.1f}' stroke='#b42318' stroke-width='2' stroke-dasharray='8 6' />"
            f"<text x='{left + 4}' y='{goal_y - 6:.1f}' font-size='12' fill='#b42318'>目标体重</text>"
        )

    return (
        f"<svg viewBox='0 0 {width} {height}' width='100%' role='img' aria-label='体重与BMI双曲线图'>"
        f"<rect x='0' y='0' width='{width}' height='{height}' rx='8' fill='#ffffff' />"
        f"{''.join(grid_lines)}{goal_line}"
        f"<polyline fill='none' stroke='#0f766e' stroke-width='3' points='{' '.join(weight_points)}' />"
        f"<polyline fill='none' stroke='#f97316' stroke-width='3' points='{' '.join(bmi_points)}' />"
        f"{''.join(point_markers)}"
        f"{x_axis_labels}"
        f"<text x='{left}' y='16' font-size='12' fill='#0f766e'>体重</text>"
        f"<text x='{width - right}' y='16' text-anchor='end' font-size='12' fill='#f97316'>BMI</text>"
        f"</svg>"
    )


def invite_admin_key_matches(submitted_key: str) -> bool:
    admin_key = app.config["INVITE_ADMIN_KEY"].strip()
    return bool(admin_key and submitted_key) and secrets.compare_digest(admin_key, submitted_key)


def admin_credentials_match(username: str, password: str) -> bool:
    if not username or not password:
        return False
    with closing(get_connection()) as connection:
        row = connection.execute(
            """
            SELECT username, password_hash
            FROM admin_credentials
            WHERE id = 1
            """
        ).fetchone()
    return bool(
        row
        and secrets.compare_digest(username, row["username"])
        and check_password_hash(row["password_hash"], password)
    )


def admin_request_authorized(submitted_key: str = "") -> bool:
    return bool(session.get("admin_authenticated")) or invite_admin_key_matches(submitted_key)


def fetch_admin_users() -> list[dict]:
    with closing(get_connection()) as connection:
        rows = connection.execute(
            """
            SELECT users.id, users.username, users.created_at, COUNT(weight_records.id) AS record_count
            FROM users
            LEFT JOIN weight_records ON weight_records.user_id = users.id
            GROUP BY users.id
            ORDER BY users.id
            """
        ).fetchall()
    return [dict(row) for row in rows]


def fetch_admin_invite_codes(limit: int = 50) -> list[dict]:
    with closing(get_connection()) as connection:
        rows = connection.execute(
            """
            SELECT invite_codes.code, invite_codes.created_at, invite_codes.used_at, users.username AS used_by
            FROM invite_codes
            LEFT JOIN users ON invite_codes.used_by_user_id = users.id
            ORDER BY invite_codes.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def admin_page_data(admin_authorized: bool) -> tuple[list[dict], list[dict]]:
    if not admin_authorized:
        return [], []
    return fetch_admin_users(), fetch_admin_invite_codes()


def set_user_password(user_id: int, password: str) -> tuple[bool, str]:
    with closing(get_connection()) as connection:
        row = connection.execute(
            "SELECT id, username FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if not row:
            return False, "账号不存在。"

        ok, message = validate_user_credentials(row["username"], password)
        if not ok:
            return False, message

        connection.execute(
            """
            UPDATE users
            SET password_hash = ?
            WHERE id = ?
            """,
            (generate_password_hash(password), user_id),
        )
        connection.commit()
    return True, f"{row['username']} 的密码已修改。"


def set_all_user_passwords(password: str) -> tuple[bool, str]:
    with closing(get_connection()) as connection:
        users = connection.execute("SELECT id, username FROM users ORDER BY id").fetchall()
        if not users:
            return False, "还没有账号。"

        for user in users:
            ok, message = validate_user_credentials(user["username"], password)
            if not ok:
                return False, message

        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            UPDATE users
            SET password_hash = ?
            """,
            (generate_password_hash(password),),
        )
        connection.commit()
    return True, f"已修改 {len(users)} 个账号的密码。"


def set_admin_password(current_password: str, new_password: str, confirm_password: str) -> tuple[bool, str]:
    with closing(get_connection()) as connection:
        row = connection.execute(
            """
            SELECT username, password_hash
            FROM admin_credentials
            WHERE id = 1
            """
        ).fetchone()
        if not row:
            return False, "管理账号不存在。"
        if not check_password_hash(row["password_hash"], current_password):
            return False, "当前管理密码错误。"
        if len(new_password) < 6:
            return False, "新管理密码至少需要 6 位。"
        if new_password != confirm_password:
            return False, "两次输入的新管理密码不一致。"

        connection.execute(
            """
            UPDATE admin_credentials
            SET password_hash = ?, updated_at = ?
            WHERE id = 1
            """,
            (generate_password_hash(new_password), datetime.now().isoformat(timespec="seconds")),
        )
        connection.commit()
    return True, "管理密码已修改。"


def render_invite_codes_page(
    message: str = "",
    invite_code: str = "",
    admin_key_value: str = "",
    admin_username_value: str = "",
    admin_authorized: bool | None = None,
    success: bool = False,
):
    if admin_authorized is None:
        admin_authorized = admin_request_authorized(admin_key_value)
    user_rows, invite_rows = admin_page_data(admin_authorized)
    return render_template_string(
        INVITE_TEMPLATE,
        message=message,
        invite_code=invite_code,
        success=success,
        admin_authorized=admin_authorized,
        admin_key_required=bool(app.config["INVITE_ADMIN_KEY"].strip()),
        admin_key_value=admin_key_value,
        admin_username_value=admin_username_value,
        current_user_id=get_current_user_id(),
        user_rows=user_rows,
        invite_rows=invite_rows,
    )


@app.get("/auth")
def auth_page():
    init_db()
    if get_current_user_id():
        return redirect(url_for("index"))
    return render_template_string(
        AUTH_TEMPLATE,
        message=request.args.get("message", ""),
        registration_enabled=app.config["REGISTRATION_ENABLED"],
    )


@app.get("/invites")
def invite_codes_page():
    init_db()
    return render_invite_codes_page(message=request.args.get("message", ""))


@app.post("/admin/authorize")
def admin_authorize_route():
    init_db()
    admin_key = request.form.get("admin_key", "")
    admin_username = request.form.get("admin_username", "").strip()
    admin_password = request.form.get("admin_password", "")
    if not invite_admin_key_matches(admin_key) and not admin_credentials_match(admin_username, admin_password):
        return render_invite_codes_page(
            message="管理账号或密码错误。",
            admin_key_value=admin_key,
            admin_username_value=admin_username,
            admin_authorized=False,
        )
    session["admin_authenticated"] = True
    return render_invite_codes_page(
        message="管理权限已验证。",
        admin_authorized=True,
        success=True,
    )


@app.post("/invites")
def create_invite_code_route():
    init_db()
    admin_key = request.form.get("admin_key", "")
    if not admin_request_authorized(admin_key):
        return render_invite_codes_page(
            message="请先登录管理界面。",
            admin_key_value=admin_key,
            admin_authorized=False,
        )
    code = create_invite_code()
    return render_invite_codes_page(
        message="邀请码已生成。",
        invite_code=code,
        admin_key_value=admin_key,
        admin_authorized=True,
        success=True,
    )


@app.post("/admin/users/<int:user_id>/password")
def set_user_password_route(user_id: int):
    init_db()
    admin_key = request.form.get("admin_key", "")
    if not admin_request_authorized(admin_key):
        return render_invite_codes_page(
            message="请先登录管理界面。",
            admin_key_value=admin_key,
            admin_authorized=False,
        )
    ok, message = set_user_password(user_id, request.form.get("password", ""))
    return render_invite_codes_page(
        message=message,
        admin_key_value=admin_key,
        admin_authorized=True,
        success=ok,
    )


@app.post("/admin/users/passwords")
def set_all_user_passwords_route():
    init_db()
    admin_key = request.form.get("admin_key", "")
    if not admin_request_authorized(admin_key):
        return render_invite_codes_page(
            message="请先登录管理界面。",
            admin_key_value=admin_key,
            admin_authorized=False,
        )
    ok, message = set_all_user_passwords(request.form.get("password", ""))
    return render_invite_codes_page(
        message=message,
        admin_key_value=admin_key,
        admin_authorized=True,
        success=ok,
    )


@app.post("/admin/password")
def set_admin_password_route():
    init_db()
    admin_key = request.form.get("admin_key", "")
    if not admin_request_authorized(admin_key):
        return render_invite_codes_page(
            message="请先登录管理界面。",
            admin_key_value=admin_key,
            admin_authorized=False,
        )
    ok, message = set_admin_password(
        request.form.get("current_password", ""),
        request.form.get("new_password", ""),
        request.form.get("confirm_password", ""),
    )
    return render_invite_codes_page(
        message=message,
        admin_key_value=admin_key,
        admin_authorized=True,
        success=ok,
    )


@app.post("/register")
def register():
    init_db()
    username = request.form.get("username", "").strip()
    if is_rate_limited("register", rate_limit_identity(username)):
        return redirect(url_for("auth_page", message="操作过于频繁，请稍后再试。"))
    if not app.config["REGISTRATION_ENABLED"]:
        return redirect(url_for("auth_page", message="当前未开放注册。"))
    ok, message = create_user_with_invite_code(
        username,
        request.form.get("password", ""),
        request.form.get("invite_code", ""),
    )
    return redirect(url_for("auth_page", message=message))


@app.post("/login")
def login():
    init_db()
    username = request.form.get("username", "").strip()
    if is_rate_limited("login", rate_limit_identity(username)):
        return redirect(url_for("auth_page", message="登录尝试过于频繁，请稍后再试。"))
    ok, message = authenticate_user(
        username,
        request.form.get("password", ""),
    )
    if ok:
        return redirect(url_for("index", message=message))
    return redirect(url_for("auth_page", message=message))


@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth_page", message="已退出登录。"))


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.route("/")
@login_required
def index():
    init_db()
    user_id = get_current_user_id()
    chart_mode = get_chart_mode(request.args.get("chart"))
    try:
        start_date, end_date = parse_filter_dates(request.args.get("start_date"), request.args.get("end_date"))
    except ValueError as exc:
        return redirect(build_redirect_url(str(exc), chart_mode=chart_mode))

    records = fetch_records(user_id, start_date, end_date)
    latest_weight, total_count, average_weight = fetch_stats(user_id, start_date, end_date)
    profile = get_profile(user_id)
    height_cm = profile["height_cm"]
    target_weight = profile["target_weight"]
    bmi_value = calculate_bmi(latest_weight, height_cm) if latest_weight is not None else None
    bmi_category = get_bmi_category(bmi_value)
    remaining_delta, remaining_status = get_remaining_delta(latest_weight, target_weight)
    progress_percent, start_weight_for_goal = get_goal_progress(records, target_weight)
    edit_id = request.args.get("edit", type=int)
    editing_record = fetch_record_by_id(edit_id, user_id) if edit_id else None
    chart_svg = build_chart_svg(records, chart_mode, target_weight)
    dual_chart_svg = build_dual_chart_svg(records, chart_mode, target_weight)
    chart_caption_map = {
        "daily": "按日展示真实记录点，支持目标体重提醒线。",
        "weekly": "按周展示平均体重，适合看阶段性趋势。",
        "monthly": "按月展示平均体重，适合看长期变化。",
    }

    return render_template_string(
        PAGE_TEMPLATE,
        message=request.args.get("message", ""),
        current_username=get_current_username(),
        records=records,
        latest_weight=latest_weight,
        total_count=total_count,
        average_weight=average_weight,
        bmi_value=bmi_value,
        bmi_category=bmi_category,
        height_cm=height_cm,
        target_weight=target_weight,
        remaining_delta=remaining_delta,
        remaining_status=remaining_status,
        progress_percent=progress_percent,
        start_weight_for_goal=start_weight_for_goal,
        chart_svg=chart_svg,
        dual_chart_svg=dual_chart_svg,
        chart_mode=chart_mode,
        chart_caption=chart_caption_map[chart_mode],
        start_date=start_date,
        end_date=end_date,
        editing_record=editing_record,
        form_record_date=editing_record["record_date"] if editing_record else date.today().isoformat(),
        form_weight=editing_record["weight"] if editing_record else "",
        form_note=editing_record["note"] if editing_record else "",
    )


@app.post("/add")
@login_required
def add_record():
    init_db()
    user_id = get_current_user_id()
    chart_mode = get_chart_mode(request.args.get("chart"))
    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()

    try:
        record_date, weight = parse_record_form(
            request.form.get("record_date", "").strip(),
            request.form.get("weight", "").strip(),
        )
    except ValueError as exc:
        return redirect(build_redirect_url(str(exc), chart_mode=chart_mode, start_date=start_date, end_date=end_date))

    with closing(get_connection()) as connection:
        connection.execute(
            """
            INSERT INTO weight_records (user_id, record_date, weight, note, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, record_date, weight, request.form.get("note", "").strip(), datetime.now().isoformat(timespec="seconds")),
        )
        connection.commit()

    return redirect(build_redirect_url("保存成功。", chart_mode=chart_mode, start_date=start_date, end_date=end_date))


@app.post("/bulk-add")
@login_required
def bulk_add_records():
    init_db()
    user_id = get_current_user_id()
    chart_mode = get_chart_mode(request.args.get("chart"))
    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()

    try:
        entries = parse_bulk_records(request.form.get("bulk_text", ""))
    except ValueError as exc:
        return redirect(build_redirect_url(str(exc), chart_mode=chart_mode, start_date=start_date, end_date=end_date))

    with closing(get_connection()) as connection:
        connection.executemany(
            """
            INSERT INTO weight_records (user_id, record_date, weight, note, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (user_id, record_date, weight, note, datetime.now().isoformat(timespec="seconds"))
                for record_date, weight, note in entries
            ],
        )
        connection.commit()
    return redirect(build_redirect_url(f"批量保存成功，共 {len(entries)} 条。", chart_mode=chart_mode, start_date=start_date, end_date=end_date))


@app.post("/update/<int:record_id>")
@login_required
def update_record(record_id: int):
    init_db()
    user_id = get_current_user_id()
    chart_mode = get_chart_mode(request.args.get("chart"))
    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()
    if not fetch_record_by_id(record_id, user_id):
        return redirect(build_redirect_url("记录不存在。", chart_mode=chart_mode, start_date=start_date, end_date=end_date))

    try:
        record_date, weight = parse_record_form(
            request.form.get("record_date", "").strip(),
            request.form.get("weight", "").strip(),
        )
    except ValueError as exc:
        return redirect(build_redirect_url(str(exc), edit_id=record_id, chart_mode=chart_mode, start_date=start_date, end_date=end_date))

    with closing(get_connection()) as connection:
        connection.execute(
            """
            UPDATE weight_records
            SET record_date = ?, weight = ?, note = ?
            WHERE id = ? AND user_id = ?
            """,
            (record_date, weight, request.form.get("note", "").strip(), record_id, user_id),
        )
        connection.commit()
    return redirect(build_redirect_url("修改成功。", chart_mode=chart_mode, start_date=start_date, end_date=end_date))


@app.post("/delete/<int:record_id>")
@login_required
def delete_record(record_id: int):
    init_db()
    user_id = get_current_user_id()
    chart_mode = get_chart_mode(request.args.get("chart"))
    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()
    with closing(get_connection()) as connection:
        connection.execute("DELETE FROM weight_records WHERE id = ? AND user_id = ?", (record_id, user_id))
        connection.commit()
    return redirect(build_redirect_url("记录已删除。", chart_mode=chart_mode, start_date=start_date, end_date=end_date))


@app.post("/profile")
@login_required
def save_profile():
    init_db()
    user_id = get_current_user_id()
    chart_mode = get_chart_mode(request.args.get("chart"))
    start_date = request.args.get("start_date", "").strip()
    end_date = request.args.get("end_date", "").strip()

    height_raw = request.form.get("height_cm", "").strip()
    target_raw = request.form.get("target_weight", "").strip()
    height_cm = None
    target_weight = None

    if height_raw:
        try:
            height_cm = float(height_raw)
        except ValueError:
            return redirect(build_redirect_url("请输入合法的身高。", chart_mode=chart_mode, start_date=start_date, end_date=end_date))
        if height_cm <= 50 or height_cm >= 260:
            return redirect(build_redirect_url("身高请填写合理范围内的厘米数。", chart_mode=chart_mode, start_date=start_date, end_date=end_date))

    if target_raw:
        try:
            target_weight = float(target_raw)
        except ValueError:
            return redirect(build_redirect_url("请输入合法的目标体重。", chart_mode=chart_mode, start_date=start_date, end_date=end_date))
        if target_weight <= 0 or target_weight >= 500:
            return redirect(build_redirect_url("目标体重请填写合理范围。", chart_mode=chart_mode, start_date=start_date, end_date=end_date))

    with closing(get_connection()) as connection:
        connection.execute(
            """
            INSERT INTO user_profiles (user_id, height_cm, target_weight)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                height_cm = excluded.height_cm,
                target_weight = excluded.target_weight
            """,
            (user_id, height_cm, target_weight),
        )
        connection.commit()
    return redirect(build_redirect_url("身体数据已保存。", chart_mode=chart_mode, start_date=start_date, end_date=end_date))


if __name__ == "__main__":
    init_db()
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "5001"))
    app.run(host=host, port=port, debug=env_bool("ALLOW_DEBUG", False))
