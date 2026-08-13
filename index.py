#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import json
import sqlite3
import time
import requests
import subprocess
import signal
import platform
from datetime import datetime

# 插件路径
PLUGIN_PATH = "/www/server/mdserver-web/plugins/mw-server-cluster"
DATA_PATH = PLUGIN_PATH + "/data"
DB_PATH = DATA_PATH + "/cluster.db"
CONFIG_PATH = PLUGIN_PATH + "/config.json"
PID_FILE = DATA_PATH + "/cluster.pid"
LOG_PATH = DATA_PATH + "/cluster.log"

# 默认配置
DEFAULT_CONFIG = {
    "db_type": "sqlite",
    "mysql_config": {
        "host": "127.0.0.1",
        "port": 3306,
        "user": "root",
        "password": "",
        "database": "mw_cluster"
    },
    "pgsql_config": {
        "host": "127.0.0.1",
        "port": 5432,
        "user": "postgres",
        "password": "",
        "database": "mw_cluster"
    },
    "mariadb_config": {
        "host": "127.0.0.1",
        "port": 3307,
        "user": "root",
        "password": "",
        "database": "mw_cluster"
    },
    "auto_start": False,
    "listen_port": 18700,
    "secret_key": "",
    "cluster_name": "默认集群",
    "sync_interval": 60
}


def init_db():
    """初始化数据库"""
    if not os.path.exists(DATA_PATH):
        os.makedirs(DATA_PATH, exist_ok=True)
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # 服务节点表
    c.execute('''CREATE TABLE IF NOT EXISTS servers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        url TEXT NOT NULL,
        api_key TEXT DEFAULT '',
        secret_key TEXT DEFAULT '',
        group_id INTEGER DEFAULT 0,
        sort_order INTEGER DEFAULT 0,
        status INTEGER DEFAULT 0,
        version TEXT DEFAULT '',
        os_info TEXT DEFAULT '',
        arch TEXT DEFAULT '',
        cpu_usage REAL DEFAULT 0,
        memory_usage REAL DEFAULT 0,
        disk_usage REAL DEFAULT 0,
        last_heartbeat DATETIME,
        remark TEXT DEFAULT '',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # 分组表
    c.execute('''CREATE TABLE IF NOT EXISTS groups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        color TEXT DEFAULT '#409EFF',
        sort_order INTEGER DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # 服务日志表
    c.execute('''CREATE TABLE IF NOT EXISTS logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        server_id INTEGER,
        action TEXT,
        message TEXT,
        status INTEGER DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # 默认分组
    c.execute("SELECT COUNT(*) FROM groups")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO groups (name, color, sort_order) VALUES (?, ?, ?)",
                  ("默认分组", "#409EFF", 0))
        c.execute("INSERT INTO groups (name, color, sort_order) VALUES (?, ?, ?)",
                  ("生产环境", "#67C23A", 1))
        c.execute("INSERT INTO groups (name, color, sort_order) VALUES (?, ?, ?)",
                  ("测试环境", "#E6A23C", 2))
    
    conn.commit()
    conn.close()


def get_config():
    """获取配置"""
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, 'r') as f:
            return json.load(f)
    return DEFAULT_CONFIG


def save_config(config):
    """保存配置"""
    with open(CONFIG_PATH, 'w') as f:
        json.dump(config, f, indent=4)


def write_log(msg, msg_type="info"):
    """写入日志"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_msg = f"[{now}] [{msg_type.upper()}] {msg}\n"
    print(log_msg, end="")
    
    if not os.path.exists(DATA_PATH):
        os.makedirs(DATA_PATH, exist_ok=True)
    
    with open(LOG_PATH, "a") as f:
        f.write(log_msg)


def get_arch():
    """获取系统架构"""
    machine = platform.machine().lower()
    if machine in ('amd64', 'x86_64'):
        return 'amd64'
    elif machine in ('aarch64', 'arm64'):
        return 'arm64'
    elif machine.startswith('arm'):
        return 'armhf'
    return machine


def get_os_info():
    """获取系统信息"""
    try:
        import distro
        return f"{distro.name()} {distro.version()}"
    except:
        try:
            with open('/etc/os-release') as f:
                for line in f:
                    if line.startswith('PRETTY_NAME='):
                        return line.split('=')[1].strip().strip('"')
        except:
            pass
    return platform.platform()


def check_server_status(url, api_key="", secret_key=""):
    """检查服务器面板状态"""
    try:
        headers = {}
        if api_key:
            headers['X-API-Key'] = api_key
        
        # 检查面板API
        check_url = url.rstrip('/') + '/api/v1/status'
        resp = requests.get(check_url, headers=headers, timeout=10, verify=False)
        
        if resp.status_code == 200:
            data = resp.json()
            return {
                "status": 1,
                "version": data.get("version", "unknown"),
                "os_info": data.get("os", ""),
                "arch": data.get("arch", ""),
                "cpu_usage": data.get("cpu", 0),
                "memory_usage": data.get("memory", 0),
                "disk_usage": data.get("disk", 0)
            }
    except Exception as e:
        write_log(f"检查服务器状态失败: {str(e)}", "error")
    
    return {"status": 0}


def get_plugin_status():
    """获取插件自身状态"""
    config = get_config()
    status = {
        "running": False,
        "pid": None,
        "port": config.get("listen_port", 18700),
        "auto_start": config.get("auto_start", False),
        "db_type": config.get("db_type", "sqlite"),
        "cluster_name": config.get("cluster_name", "默认集群"),
        "arch": get_arch(),
        "os_info": get_os_info()
    }
    
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, 'r') as f:
                pid = int(f.read().strip())
            os.kill(pid, 0)
            status["running"] = True
            status["pid"] = pid
        except:
            pass
    
    return status


def start_service():
    """启动服务"""
    if get_plugin_status()["running"]:
        return {"status": False, "msg": "服务已在运行中"}
    
    try:
        pid = os.fork()
        if pid == 0:
            # 子进程
            import http.server
            import socketserver
            
            config = get_config()
            port = config.get("listen_port", 18700)
            
            # 写入PID
            with open(PID_FILE, 'w') as f:
                f.write(str(os.getpid()))
            
            # 启动HTTP服务
            handler = http.server.SimpleHTTPRequestHandler
            httpd = socketserver.TCPServer(("", port), handler)
            write_log(f"集群管理服务启动在端口: {port}")
            httpd.serve_forever()
        else:
            # 父进程
            time.sleep(0.5)
            if get_plugin_status()["running"]:
                return {"status": True, "msg": "服务启动成功"}
            else:
                return {"status": False, "msg": "服务启动失败"}
    except Exception as e:
        write_log(f"启动服务失败: {str(e)}", "error")
        return {"status": False, "msg": f"启动失败: {str(e)}"}


def stop_service():
    """停止服务"""
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, 'r') as f:
                pid = int(f.read().strip())
            os.kill(pid, signal.SIGTERM)
            os.remove(PID_FILE)
            write_log("集群管理服务已停止")
            return {"status": True, "msg": "服务已停止"}
        except Exception as e:
            write_log(f"停止服务失败: {str(e)}", "error")
            return {"status": False, "msg": f"停止失败: {str(e)}"}
    return {"status": True, "msg": "服务未运行"}


def restart_service():
    """重启服务"""
    stop_service()
    time.sleep(1)
    return start_service()


def reload_config():
    """重载配置"""
    write_log("配置已重载")
    return {"status": True, "msg": "配置已重载"}


# ===== API 接口函数 =====

def get_servers_list():
    """获取服务器列表"""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    c.execute('''SELECT s.*, g.name as group_name, g.color as group_color 
                 FROM servers s 
                 LEFT JOIN groups g ON s.group_id = g.id 
                 ORDER BY g.sort_order, s.sort_order''')
    
    servers = []
    for row in c.fetchall():
        server = dict(row)
        servers.append(server)
    
    conn.close()
    return {"status": True, "data": servers}


def get_groups_list():
    """获取分组列表"""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    c.execute('''SELECT g.*, (SELECT COUNT(*) FROM servers WHERE group_id = g.id) as server_count 
                 FROM groups g ORDER BY g.sort_order''')
    
    groups = []
    for row in c.fetchall():
        group = dict(row)
        groups.append(group)
    
    conn.close()
    return {"status": True, "data": groups}


def add_server(params):
    """添加服务器"""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # 检查URL是否已存在
    c.execute("SELECT id FROM servers WHERE url = ?", (params.get("url"),))
    if c.fetchone():
        conn.close()
        return {"status": False, "msg": "该服务器地址已存在"}
    
    # 检查服务器状态
    status_info = check_server_status(
        params.get("url", ""),
        params.get("api_key", ""),
        params.get("secret_key", "")
    )
    
    c.execute('''INSERT INTO servers (name, url, api_key, secret_key, group_id, sort_order, status,
                 version, os_info, arch, cpu_usage, memory_usage, disk_usage, last_heartbeat, remark)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
              (params.get("name"),
               params.get("url"),
               params.get("api_key", ""),
               params.get("secret_key", ""),
               params.get("group_id", 1),
               0,  # sort_order will be updated
               status_info.get("status", 0),
               status_info.get("version", ""),
               status_info.get("os_info", ""),
               status_info.get("arch", ""),
               status_info.get("cpu_usage", 0),
               status_info.get("memory_usage", 0),
               status_info.get("disk_usage", 0),
               datetime.now().strftime("%Y-%m-%d %H:%M:%S") if status_info.get("status") else None,
               params.get("remark", "")))
    
    server_id = c.lastrowid
    
    # 更新排序
    c.execute("UPDATE servers SET sort_order = ? WHERE id = ?", (server_id, server_id))
    
    conn.commit()
    conn.close()
    
    write_log(f"添加服务器: {params.get('name')} ({params.get('url')})")
    return {"status": True, "msg": "添加成功", "data": {"id": server_id}}


def delete_server(server_id):
    """删除服务器"""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute("DELETE FROM servers WHERE id = ?", (server_id,))
    c.execute("DELETE FROM logs WHERE server_id = ?", (server_id,))
    
    conn.commit()
    conn.close()
    
    write_log(f"删除服务器 ID: {server_id}")
    return {"status": True, "msg": "删除成功"}


def update_server(server_id, params):
    """更新服务器"""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    fields = []
    values = []
    
    updateable = ["name", "url", "api_key", "secret_key", "group_id", "sort_order",
                  "remark", "status", "version", "os_info", "arch",
                  "cpu_usage", "memory_usage", "disk_usage"]
    
    for field in updateable:
        if field in params:
            fields.append(f"{field} = ?")
            values.append(params[field])
    
    if fields:
        fields.append("updated_at = ?")
        values.append(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        values.append(server_id)
        
        c.execute(f"UPDATE servers SET {', '.join(fields)} WHERE id = ?", values)
        conn.commit()
    
    conn.close()
    return {"status": True, "msg": "更新成功"}


def add_group(params):
    """添加分组"""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute("SELECT MAX(sort_order) FROM groups")
    max_order = c.fetchone()[0] or 0
    
    c.execute("INSERT INTO groups (name, color, sort_order) VALUES (?, ?, ?)",
              (params.get("name"), params.get("color", "#409EFF"), max_order + 1))
    
    group_id = c.lastrowid
    conn.commit()
    conn.close()
    
    return {"status": True, "msg": "分组添加成功", "data": {"id": group_id}}


def delete_group(group_id):
    """删除分组"""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # 将属于该分组的服务器移到默认分组
    c.execute("UPDATE servers SET group_id = 1 WHERE group_id = ?", (group_id,))
    c.execute("DELETE FROM groups WHERE id = ?", (group_id,))
    
    conn.commit()
    conn.close()
    
    return {"status": True, "msg": "分组删除成功"}


def update_group(group_id, params):
    """更新分组"""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    if "name" in params:
        c.execute("UPDATE groups SET name = ? WHERE id = ?", (params["name"], group_id))
    if "color" in params:
        c.execute("UPDATE groups SET color = ? WHERE id = ?", (params["color"], group_id))
    if "sort_order" in params:
        c.execute("UPDATE groups SET sort_order = ? WHERE id = ?", (params["sort_order"], group_id))
    
    conn.commit()
    conn.close()
    
    return {"status": True, "msg": "分组更新成功"}


def update_server_order(params):
    """更新服务器排序（拖拽）"""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    for item in params.get("order", []):
        c.execute("UPDATE servers SET sort_order = ?, group_id = ? WHERE id = ?",
                  (item.get("sort_order", 0), item.get("group_id", 1), item.get("id")))
    
    conn.commit()
    conn.close()
    
    return {"status": True, "msg": "排序更新成功"}


def check_server(server_id):
    """检查指定服务器状态"""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute("SELECT * FROM servers WHERE id = ?", (server_id,))
    row = c.fetchone()
    
    if not row:
        conn.close()
        return {"status": False, "msg": "服务器不存在"}
    
    server = {
        "id": row[0],
        "name": row[1],
        "url": row[2],
        "api_key": row[3],
        "secret_key": row[4]
    }
    
    status_info = check_server_status(server["url"], server["api_key"], server["secret_key"])
    
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute('''UPDATE servers SET status=?, version=?, os_info=?, arch=?,
                 cpu_usage=?, memory_usage=?, disk_usage=?, last_heartbeat=?, updated_at=?
                 WHERE id=?''',
              (status_info.get("status", 0),
               status_info.get("version", ""),
               status_info.get("os_info", ""),
               status_info.get("arch", ""),
               status_info.get("cpu_usage", 0),
               status_info.get("memory_usage", 0),
               status_info.get("disk_usage", 0),
               now, now, server_id))
    
    conn.commit()
    conn.close()
    
    return {"status": True, "data": status_info}


def check_all_servers():
    """检查所有服务器状态"""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute("SELECT id, name, url, api_key, secret_key FROM servers")
    servers = c.fetchall()
    
    results = []
    for server in servers:
        status_info = check_server_status(server[2], server[3], server[4])
        
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute('''UPDATE servers SET status=?, version=?, os_info=?, arch=?,
                     cpu_usage=?, memory_usage=?, disk_usage=?, last_heartbeat=?, updated_at=?
                     WHERE id=?''',
                  (status_info.get("status", 0),
                   status_info.get("version", ""),
                   status_info.get("os_info", ""),
                   status_info.get("arch", ""),
                   status_info.get("cpu_usage", 0),
                   status_info.get("memory_usage", 0),
                   status_info.get("disk_usage", 0),
                   now, now, server[0]))
        
        results.append({
            "id": server[0],
            "name": server[1],
            "status": status_info
        })
    
    conn.commit()
    conn.close()
    
    return {"status": True, "data": results}


def get_installed_databases():
    """获取已安装的数据库服务"""
    databases = {}
    
    # 检查MySQL
    mysql_paths = [
        "/www/server/mysql",
        "/www/server/mysql57",
        "/www/server/mysql80",
        "/etc/mysql"
    ]
    for path in mysql_paths:
        if os.path.exists(path):
            databases["mysql"] = {
                "installed": True,
                "path": path,
                "version": "unknown"
            }
            # 尝试获取版本
            version_file = os.path.join(path, "version.txt")
            if os.path.exists(version_file):
                with open(version_file) as f:
                    databases["mysql"]["version"] = f.read().strip()
            break
    
    # 检查MariaDB
    mariadb_paths = [
        "/www/server/mariadb",
        "/www/server/mariadb10",
        "/etc/mariadb"
    ]
    for path in mariadb_paths:
        if os.path.exists(path):
            databases["mariadb"] = {
                "installed": True,
                "path": path,
                "version": "unknown"
            }
            version_file = os.path.join(path, "version.txt")
            if os.path.exists(version_file):
                with open(version_file) as f:
                    databases["mariadb"]["version"] = f.read().strip()
            break
    
    # 检查PostgreSQL
    pgsql_paths = [
        "/www/server/postgresql",
        "/var/lib/pgsql",
        "/etc/postgresql"
    ]
    for path in pgsql_paths:
        if os.path.exists(path):
            databases["pgsql"] = {
                "installed": True,
                "path": path,
                "version": "unknown"
            }
            version_file = os.path.join(path, "version.txt")
            if os.path.exists(version_file):
                with open(version_file) as f:
                    databases["pgsql"]["version"] = f.read().strip()
            break
    
    # 检查命令行
    try:
        import subprocess
        result = subprocess.run(["mysql", "--version"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            if "mysql" not in databases:
                databases["mysql"] = {"installed": True, "path": "system", "version": "unknown"}
            databases["mysql"]["version"] = result.stdout.strip()
    except:
        pass
    
    try:
        result = subprocess.run(["mariadb", "--version"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            if "mariadb" not in databases:
                databases["mariadb"] = {"installed": True, "path": "system", "version": "unknown"}
            databases["mariadb"]["version"] = result.stdout.strip()
    except:
        pass
    
    try:
        result = subprocess.run(["psql", "--version"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            if "pgsql" not in databases:
                databases["pgsql"] = {"installed": True, "path": "system", "version": "unknown"}
            databases["pgsql"]["version"] = result.stdout.strip()
    except:
        pass
    
    return {"status": True, "data": databases}


def set_database_config(params):
    """设置数据库配置"""
    config = get_config()
    
    db_type = params.get("db_type", "")
    
    if db_type == "mysql" or db_type == "all":
        config["mysql_config"] = {
            "host": params.get("mysql_host", "127.0.0.1"),
            "port": int(params.get("mysql_port", 3306)),
            "user": params.get("mysql_user", "root"),
            "password": params.get("mysql_password", ""),
            "database": params.get("mysql_database", "mw_cluster")
        }
    
    if db_type == "pgsql" or db_type == "all":
        config["pgsql_config"] = {
            "host": params.get("pgsql_host", "127.0.0.1"),
            "port": int(params.get("pgsql_port", 5432)),
            "user": params.get("pgsql_user", "postgres"),
            "password": params.get("pgsql_password", ""),
            "database": params.get("pgsql_database", "mw_cluster")
        }
    
    if db_type == "mariadb" or db_type == "all":
        config["mariadb_config"] = {
            "host": params.get("mariadb_host", "127.0.0.1"),
            "port": int(params.get("mariadb_port", 3307)),
            "user": params.get("mariadb_user", "root"),
            "password": params.get("mariadb_password", ""),
            "database": params.get("mariadb_database", "mw_cluster")
        }
    
    if params.get("active_db") in ["mysql", "pgsql", "mariadb"]:
        config["db_type"] = params.get("active_db")
    
    save_config(config)
    write_log(f"数据库配置已更新: {db_type}")
    
    return {"status": True, "msg": "数据库配置已保存"}


def test_db_connection(params):
    """测试数据库连接"""
    db_type = params.get("db_type", "mysql")
    config = get_config()
    
    if db_type == "mysql":
        db_config = config.get("mysql_config", params)
    elif db_type == "pgsql":
        db_config = config.get("pgsql_config", params)
    elif db_type == "mariadb":
        db_config = config.get("mariadb_config", params)
    else:
        db_config = params
    
    try:
        if db_type in ("mysql", "mariadb"):
            import pymysql
            conn = pymysql.connect(
                host=db_config.get("host", "127.0.0.1"),
                port=int(db_config.get("port", 3306)),
                user=db_config.get("user", "root"),
                password=db_config.get("password", ""),
                database=db_config.get("database", "mysql"),
                connect_timeout=5
            )
            conn.close()
            return {"status": True, "msg": "数据库连接成功"}
        
        elif db_type == "pgsql":
            import psycopg2
            conn = psycopg2.connect(
                host=db_config.get("host", "127.0.0.1"),
                port=int(db_config.get("port", 5432)),
                user=db_config.get("user", "postgres"),
                password=db_config.get("password", ""),
                dbname=db_config.get("database", "postgres"),
                connect_timeout=5
            )
            conn.close()
            return {"status": True, "msg": "数据库连接成功"}
    
    except Exception as e:
        return {"status": False, "msg": f"连接失败: {str(e)}"}
    
    return {"status": False, "msg": "不支持的数据库类型"}


def get_logs(server_id=None, limit=100):
    """获取日志"""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    if server_id:
        c.execute("SELECT * FROM logs WHERE server_id = ? ORDER BY created_at DESC LIMIT ?",
                  (server_id, limit))
    else:
        c.execute("SELECT * FROM logs ORDER BY created_at DESC LIMIT ?", (limit,))
    
    logs = []
    for row in c.fetchall():
        logs.append(dict(row))
    
    conn.close()
    return {"status": True, "data": logs}


# ===== 主入口 =====

def main():
    """主函数"""
    action = sys.argv[1] if len(sys.argv) > 1 else "status"
    
    if action == "status":
        result = get_plugin_status()
    elif action == "start":
        result = start_service()
    elif action == "stop":
        result = stop_service()
    elif action == "restart":
        result = restart_service()
    elif action == "reload":
        result = reload_config()
    elif action == "get_servers":
        result = get_servers_list()
    elif action == "get_groups":
        result = get_groups_list()
    elif action == "add_server":
        params = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
        result = add_server(params)
    elif action == "delete_server":
        server_id = int(sys.argv[2]) if len(sys.argv) > 2 else 0
        result = delete_server(server_id)
    elif action == "update_server":
        server_id = int(sys.argv[2]) if len(sys.argv) > 2 else 0
        params = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
        result = update_server(server_id, params)
    elif action == "add_group":
        params = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
        result = add_group(params)
    elif action == "delete_group":
        group_id = int(sys.argv[2]) if len(sys.argv) > 2 else 0
        result = delete_group(group_id)
    elif action == "update_group":
        group_id = int(sys.argv[2]) if len(sys.argv) > 2 else 0
        params = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
        result = update_group(group_id, params)
    elif action == "update_server_order":
        params = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
        result = update_server_order(params)
    elif action == "check_server":
        server_id = int(sys.argv[2]) if len(sys.argv) > 2 else 0
        result = check_server(server_id)
    elif action == "check_all":
        result = check_all_servers()
    elif action == "get_databases":
        result = get_installed_databases()
    elif action == "set_db_config":
        params = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
        result = set_database_config(params)
    elif action == "test_db":
        params = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
        result = test_db_connection(params)
    elif action == "get_logs":
        server_id = int(sys.argv[2]) if len(sys.argv) > 2 else None
        limit = int(sys.argv[3]) if len(sys.argv) > 3 else 100
        result = get_logs(server_id, limit)
    elif action == "get_config":
        result = {"status": True, "data": get_config()}
    elif action == "save_config":
        params = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
        config = get_config()
        config.update(params)
        save_config(config)
        result = {"status": True, "msg": "配置已保存"}
    else:
        result = {"status": False, "msg": f"未知操作: {action}"}
    
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    # 初始化
    init_db()
    main()
