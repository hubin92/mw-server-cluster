// 插件API接口基路径
const API_BASE = '/plugin?p=mw-server-cluster&a=';

new Vue({
    el: '#app',
    data() {
        return {
            // 插件状态
            pluginStatus: {
                running: false,
                pid: null,
                port: 18700,
                auto_start: false,
                db_type: 'sqlite',
                arch: 'amd64',
                cluster_name: '默认集群'
            },
            autoStartEnabled: false,
            operating: false,
            checkingAll: false,
            submitting: false,
            testingDb: false,

            // 服务器数据
            servers: [],
            groups: [],
            activeGroup: 'all',

            // 对话框
            serverDialogVisible: false,
            serverDialogTitle: '添加服务器',
            serverForm: {
                id: null,
                name: '',
                url: '',
                api_key: '',
                secret_key: '',
                group_id: 1,
                remark: ''
            },
            serverRules: {
                name: [{ required: true, message: '请输入服务器名称', trigger: 'blur' }],
                url: [{ required: true, message: '请输入面板地址', trigger: 'blur' }]
            },
            isEditingServer: false,

            groupDialogVisible: false,
            groupForm: {
                name: '',
                color: '#409EFF'
            },

            settingsDialogVisible: false,
            settingsTab: 'main',
            settingsForm: {
                cluster_name: '默认集群',
                listen_port: 18700,
                sync_interval: 60,
                db_type: 'sqlite'
            },
            dbConfigs: {
                mysql: { host: '127.0.0.1', port: 3306, user: 'root', password: '', database: 'mw_cluster' },
                pgsql: { host: '127.0.0.1', port: 5432, user: 'postgres', password: '', database: 'mw_cluster' },
                mariadb: { host: '127.0.0.1', port: 3307, user: 'root', password: '', database: 'mw_cluster' }
            },
            subPanelConfig: {
                api_url: '',
                api_key: '',
                sync_interval: 60
            }
        };
    },
    computed: {
        filteredServers() {
            if (this.activeGroup === 'all') {
                return this.servers;
            }
            const groupId = parseInt(this.activeGroup.replace('group-', ''));
            return this.servers.filter(s => s.group_id === groupId);
        }
    },
    mounted() {
        this.init();
    },
    methods: {
        async init() {
            await this.loadPluginStatus();
            await this.loadGroups();
            await this.loadServers();
            await this.loadConfig();
        },

        // API 请求封装
        async callApi(action, params = {}) {
            try {
                const url = API_BASE + action;
                const formData = new FormData();
                formData.append('data', JSON.stringify(params));
                
                const response = await fetch(url, {
                    method: 'POST',
                    body: formData
                });
                return await response.json();
            } catch (e) {
                console.error('API Error:', e);
                this.$message.error('请求失败: ' + e.message);
                return { status: false, msg: e.message };
            }
        },

        async callPython(action, ...args) {
            try {
                let url = API_BASE + 'run_action';
                const formData = new FormData();
                formData.append('action', action);
                if (args.length > 0) {
                    formData.append('params', JSON.stringify(args));
                }
                
                const response = await fetch(url, {
                    method: 'POST',
                    body: formData
                });
                return await response.json();
            } catch (e) {
                console.error('Python API Error:', e);
                return { status: false, msg: e.message };
            }
        },

        // 加载插件状态
        async loadPluginStatus() {
            const result = await this.callApi('get_status');
            if (result.status) {
                this.pluginStatus = result.data;
                this.autoStartEnabled = result.data.auto_start;
            }
        },

        // 加载分组
        async loadGroups() {
            const result = await this.callApi('get_groups');
            if (result.status) {
                this.groups = result.data;
            }
        },

        // 加载服务器列表
        async loadServers() {
            const result = await this.callApi('get_servers');
            if (result.status) {
                this.servers = result.data;
            }
        },

        // 加载配置
        async loadConfig() {
            const result = await this.callApi('get_config');
            if (result.status) {
                const config = result.data;
                this.settingsForm.cluster_name = config.cluster_name || '默认集群';
                this.settingsForm.listen_port = config.listen_port || 18700;
                this.settingsForm.sync_interval = config.sync_interval || 60;
                this.settingsForm.db_type = config.db_type || 'sqlite';
                
                if (config.mysql_config) {
                    this.dbConfigs.mysql = { ...this.dbConfigs.mysql, ...config.mysql_config };
                }
                if (config.pgsql_config) {
                    this.dbConfigs.pgsql = { ...this.dbConfigs.pgsql, ...config.pgsql_config };
                }
                if (config.mariadb_config) {
                    this.dbConfigs.mariadb = { ...this.dbConfigs.mariadb, ...config.mariadb_config };
                }
            }
        },

        // 服务控制
        async startPlugin() {
            this.operating = true;
            const result = await this.callApi('start');
            if (result.status) {
                this.$message.success('服务启动成功');
                await this.loadPluginStatus();
            } else {
                this.$message.error(result.msg || '启动失败');
            }
            this.operating = false;
        },

        async stopPlugin() {
            this.operating = true;
            const result = await this.callApi('stop');
            if (result.status) {
                this.$message.success('服务已停止');
                await this.loadPluginStatus();
            } else {
                this.$message.error(result.msg || '停止失败');
            }
            this.operating = false;
        },

        async restartPlugin() {
            this.operating = true;
            const result = await this.callApi('restart');
            if (result.status) {
                this.$message.success('服务已重启');
                await this.loadPluginStatus();
            } else {
                this.$message.error(result.msg || '重启失败');
            }
            this.operating = false;
        },

        async reloadPlugin() {
            this.operating = true;
            const result = await this.callApi('reload');
            if (result.status) {
                this.$message.success('配置已重载');
            } else {
                this.$message.error(result.msg || '重载失败');
            }
            this.operating = false;
        },

        // 自启动切换
        async toggleAutoStart(val) {
            const result = await this.callApi('set_auto_start', { enabled: val });
            if (result.status) {
                this.$message.success(val ? '自启动已开启' : '自启动已关闭');
            } else {
                this.autoStartEnabled = !val;
                this.$message.error(result.msg || '设置失败');
            }
        },

        // 分组切换
        handleGroupClick() {},

        // 拖拽结束
        async onDragEnd(evt) {
            const orderData = this.filteredServers.map((server, index) => ({
                id: server.id,
                sort_order: index,
                group_id: server.group_id
            }));
            
            const result = await this.callApi('update_order', { order: orderData });
            if (result.status) {
                this.$message.success('排序已更新');
            }
        },

        // 检测所有服务器
        async checkAllServers() {
            this.checkingAll = true;
            const result = await this.callApi('check_all');
            if (result.status) {
                this.$message.success('状态检测完成');
                await this.loadServers();
            } else {
                this.$message.error(result.msg || '检测失败');
            }
            this.checkingAll = false;
        },

        // 检测单个服务器
        async checkServer(serverId) {
            const result = await this.callApi('check_server', { id: serverId });
            if (result.status) {
                this.$message.success('检测完成');
                await this.loadServers();
            } else {
                this.$message.error(result.msg || '检测失败');
            }
        },

        // 添加服务器对话框
        showAddServerDialog() {
            this.isEditingServer = false;
            this.serverDialogTitle = '添加服务器';
            this.serverForm = {
                id: null,
                name: '',
                url: '',
                api_key: '',
                secret_key: '',
                group_id: this.groups.length > 0 ? this.groups[0].id : 1,
                remark: ''
            };
            this.serverDialogVisible = true;
        },

        // 编辑服务器对话框
        showEditServerDialog(server) {
            this.isEditingServer = true;
            this.serverDialogTitle = '编辑服务器';
            this.serverForm = {
                id: server.id,
                name: server.name,
                url: server.url,
                api_key: server.api_key || '',
                secret_key: server.secret_key || '',
                group_id: server.group_id,
                remark: server.remark || ''
            };
            this.serverDialogVisible = true;
        },

        // 提交服务器
        async submitServer() {
            this.$refs.serverForm.validate(async (valid) => {
                if (!valid) return;
                
                this.submitting = true;
                let result;
                
                if (this.isEditingServer) {
                    result = await this.callApi('update_server', {
                        id: this.serverForm.id,
                        ...this.serverForm
                    });
                } else {
                    result = await this.callApi('add_server', this.serverForm);
                }
                
                if (result.status) {
                    this.$message.success(this.isEditingServer ? '更新成功' : '添加成功');
                    this.serverDialogVisible = false;
                    await this.loadServers();
                } else {
                    this.$message.error(result.msg || '操作失败');
                }
                this.submitting = false;
            });
        },

        // 删除服务器
        async deleteServer(server) {
            this.$confirm(`确定要删除服务器 "${server.name}" 吗？`, '提示', {
                confirmButtonText: '确定',
                cancelButtonText: '取消',
                type: 'warning'
            }).then(async () => {
                const result = await this.callApi('delete_server', { id: server.id });
                if (result.status) {
                    this.$message.success('删除成功');
                    await this.loadServers();
                } else {
                    this.$message.error(result.msg || '删除失败');
                }
            }).catch(() => {});
        },

        // 添加分组对话框
        showAddGroupDialog() {
            this.groupForm = { name: '', color: '#409EFF' };
            this.groupDialogVisible = true;
        },

        // 提交分组
        async submitGroup() {
            if (!this.groupForm.name) {
                this.$message.warning('请输入分组名称');
                return;
            }
            
            this.submitting = true;
            const result = await this.callApi('add_group', this.groupForm);
            if (result.status) {
                this.$message.success('分组添加成功');
                this.groupDialogVisible = false;
                await this.loadGroups();
            } else {
                this.$message.error(result.msg || '添加失败');
            }
            this.submitting = false;
        },

        // 设置对话框
        async showSettingsDialog() {
            await this.loadConfig();
            this.settingsDialogVisible = true;
        },

        // 保存设置
        async saveSettings() {
            this.submitting = true;
            
            const params = {
                cluster_name: this.settingsForm.cluster_name,
                listen_port: this.settingsForm.listen_port,
                sync_interval: this.settingsForm.sync_interval,
                db_type: this.settingsForm.db_type,
                mysql_config: this.dbConfigs.mysql,
                pgsql_config: this.dbConfigs.pgsql,
                mariadb_config: this.dbConfigs.mariadb
            };
            
            const result = await this.callApi('save_config', params);
            if (result.status) {
                this.$message.success('设置已保存');
                await this.loadPluginStatus();
            } else {
                this.$message.error(result.msg || '保存失败');
            }
            this.submitting = false;
        },

        // 测试数据库连接
        async testDbConnection(dbType) {
            this.testingDb = true;
            
            let params = { db_type: dbType };
            if (dbType === 'mysql') {
                params = { ...params, ...this.dbConfigs.mysql };
            } else if (dbType === 'pgsql') {
                params = { ...params, ...this.dbConfigs.pgsql };
            } else if (dbType === 'mariadb') {
                params = { ...params, ...this.dbConfigs.mariadb };
            }
            
            const result = await this.callApi('test_db', params);
            if (result.status) {
                this.$message.success('数据库连接成功');
            } else {
                this.$message.error(result.msg || '连接失败');
            }
            this.testingDb = false;
        },

        // 保存子面板配置
        async saveSubPanelConfig() {
            this.submitting = true;
            const result = await this.callApi('save_subpanel_config', this.subPanelConfig);
            if (result.status) {
                this.$message.success('子面板配置已保存');
            } else {
                this.$message.error(result.msg || '保存失败');
            }
            this.submitting = false;
        }
    }
});
