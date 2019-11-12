---
title: android init源码阅读
date: 2019-11-11 18:06:17
tags: [android, init]
---

init程序是第一个执行的用户空间程序, 从而启动了整个Android世界. 同时init也是整个Android的"父进程", 监控管理这个所有的进程. 
<!-- more  -->

# 流程简述

源码入口位于system/core/init, Android.bp中定义了程序名字为"init\_defaults"。 
	```cpp
    int main(int argc, char** argv) {
    	// 启动模式可以选择eventd和watchdogd模式
    	if (!strcmp(basename(argv[0]), "ueventd")) {
    		return ueventd_main(argc, argv);
    	}
    
    	if (!strcmp(basename(argv[0]), "watchdogd")) {
    		return watchdogd_main(argc, argv);
    	}
    
    	if (REBOOT_BOOTLOADER_ON_PANIC) {
    		InstallRebootSignalHandlers();
    	}
    	add_environment("PATH", _PATH_DEFPATH);
    	// xxxx
    }
	```

## first stage (第一阶段)

-   首先进行mount
-   初始化内核日志模块
-   初始化SeLinux
-   设置环境变量 INIT\_SECOND\_STAGE 为 true
-   execv重新执行 init程序， 进入第二阶段


## second stage (第二阶段)

-   重新初始化内核日志模块
-   初始化属性服务器 property\_init(), 稍后启动
-   初始化信号值 signal\_handler\_init()
-   初始化ActionManager, ServiceManager(不要跟Binder的ServiceManager弄混了， 不是一个)
-   构造Parser开始解析"ro.boot.init\_rc"脚本
-   am触发early-init事件, 添加内置Action, 触发init事件，触发late-init事件
-   无限循环判断ServerManager是否需要执行, 闲时epoll等待


# 属性服务器(property\_service)
	```cpp
    void start_property_service() {
    	property_set("ro.property_service.version", "2");
    
    	property_set_fd = CreateSocket(PROP_SERVICE_NAME, SOCK_STREAM | SOCK_CLOEXEC | SOCK_NONBLOCK,
    								   false, 0666, 0, 0, nullptr, sehandle);
    	if (property_set_fd == -1) {
    		PLOG(ERROR) << "start_property_service socket creation failed";
    		exit(1);
    	}
    
    	listen(property_set_fd, 8);
    
    	register_epoll_handler(property_set_fd, handle_property_set_fd);
    }
	```

创建了一个UNIX socket, 用于更新properties. 当属性被设置后: 

	```cpp
    // init.cpp
    void property_changed(const std::string& name, const std::string& value) {
    	if (name == "sys.powerctl") {
    		shutdown_command = value;
    		do_shutdown = true;
    	}
    	if (property_triggers_enabled) ActionManager::GetInstance().QueuePropertyChange(name, value);
    	if (waiting_for_prop) {
    		if (wait_prop_name == name && wait_prop_value == value) {
    			LOG(INFO) << "Wait for property took " << *waiting_for_prop;
    			ResetWaitForProp();
    		}
    	}
    }
	```

QueuePropertyChange代表消息进入队列, 后续将分配给对应的Action执行。 具体的参见下文(实际上就是一个触发器(trigger)). 


# init.rc语法

init.rc的语法文档就是init程序的README.md文档。 有五大命令: Actions, Commands, Services, Options, Improts. 其中Actions与Services同时隐性的声明了一个Section. 

Actions是一系列命令的名字, Actions有一个触发器(trigger), 用于指定这个Action什么时候被执行. 
	
	```sh
    on <trigger> [&& <trigger>]*
       <command>
       <command>
       <command>
	```

Services是一个由init启动或者重启的程序，如下: 
	```sh
    service <name> <pathname> [ <argument> ]*
       <option>
       <option>
       ...
	```

options一项包含如下: 

-   console [<console>]: 这个服务需要一个console
-   critical: 至关重要的服务, 如果四分钟内重启超过四次，重启进入recovery模式.
-   disabled: 需要手动启动， 不会自动启动
-   setenv <name> <value>: 设置启动服务器时的环境变量
-   socket <name> <type> <perm> [ <user> [<group> [seclabel]]] 创建一个unix socket并传给启动进程
-   file <path> <type> 打开一个文件
-   user <username> 执行这个服务前， 首先切换到这个用户
-   oneshot: 不要重启
-   class:
-   onrestart: 重启时执行的命令
-   writepid: 将pid写到文件中

Imports <path> 用于解析一个配置文件


# init.rc的解析与执行

解析语法相关的代码位于/system/core/init/init\_parser.h的Parser, 首先将init.rc分成多个Section, 对应的SectionParser进行解析, 对应关系如下: 

-   service: ServiceParser
-   on: ActionParser
-   import: ImportParser(略)

先看一下Parser是如何解析的. 

	```
    // system/core/init/init_parser.cpp
    void Parser::ParseData(const std::string& filename, const std::string& data) {
    	//TODO: Use a parser with const input and remove this copy
    	std::vector<char> data_copy(data.begin(), data.end());
    	data_copy.push_back('\0');
    
    	parse_state state;
    	state.line = 0;
    	state.ptr = &data_copy[0];
    	state.nexttoken = 0;
    
    	SectionParser* section_parser = nullptr;
    	std::vector<std::string> args;
    
    	for (;;) {
    		// next_token位于parser.cpp文件中, 可以简单理解成解析单词，EOF结尾, 换行. 自动排除注释(没啥特别的)
    		switch (next_token(&state)) {
    		case T_EOF:
    			if (section_parser) {
    				section_parser->EndSection();
    			}
    			return;
    		case T_NEWLINE:
    			state.line++;
    			if (args.empty()) {
    				break;
    			}
    			// If we have a line matching a prefix we recognize, call its callback and unset any
    			// current section parsers.  This is meant for /sys/ and /dev/ line entries for uevent.
    			// 这个line_callbacks只在uevent中使用了, 正常流程可以忽略它
    			for (const auto& [prefix, callback] : line_callbacks_) {
    				if (android::base::StartsWith(args[0], prefix.c_str())) {
    					if (section_parser) section_parser->EndSection();
    
    					std::string ret_err;
    					if (!callback(std::move(args), &ret_err)) {
    						LOG(ERROR) << filename << ": " << state.line << ": " << ret_err;
    					}
    					section_parser = nullptr;
    					break;
    				}
    			}
    			if (section_parsers_.count(args[0])) {
    				if (section_parser) {
    					section_parser->EndSection();
    				}
    				section_parser = section_parsers_[args[0]].get();
    				std::string ret_err;
    				// 就此由SectionParser接手解析
    				if (!section_parser->ParseSection(std::move(args), filename, state.line, &ret_err)) {
    					LOG(ERROR) << filename << ": " << state.line << ": " << ret_err;
    					section_parser = nullptr;
    				}
    			} else if (section_parser) {
    				std::string ret_err;
    				if (!section_parser->ParseLineSection(std::move(args), state.line, &ret_err)) {
    					LOG(ERROR) << filename << ": " << state.line << ": " << ret_err;
    				}
    			}
    			args.clear();
    			break;
    		case T_TEXT:
    			args.emplace_back(state.text);
    			break;
    		}
    	}
    }
	```

ActionParser如何ParseSection, 由ActionParse::InitTriggers实现: 
	```cpp
    bool Action::InitTriggers(const std::vector<std::string>& args, std::string* err) {
    	const static std::string prop_str("property:");
    	for (std::size_t i = 0; i < args.size(); ++i) {
    		if (args[i].empty()) {
    			*err = "empty trigger is not valid";
    			return false;
    		}
    
    		if (i % 2) {
    			if (args[i] != "&&") {
    				*err = "&& is the only symbol allowed to concatenate actions";
    				return false;
    			} else {
    				continue;
    			}
    		}
    
    		if (!args[i].compare(0, prop_str.length(), prop_str)) {
    			if (!ParsePropertyTrigger(args[i], err)) {
    				return false;
    			}
    		} else {
    			if (!event_trigger_.empty()) {
    				*err = "multiple event triggers are not allowed";
    				return false;
    			}
    			// 这里记录这个Action的触发器名字, 比如on boot 中boot.
    			event_trigger_ = args[i];
    		}
    	}
    
    	return true;
    }
	
	```

在ParsePropertyTrigger中, 将对应关系记录在Action的property\_triggers\_(是一个Map, key是属性名, value是其值)中.

ServiceParser如何ParseSection: 直接构造了一个Service对象而已, 然后PaseLine函数代理给了OptionParserMap这个类，设置Service的各种属性. 

init.rc有很多内置方法, 定义在system/core/init/builtins.cpp中, 包括mount, chmod, chown, copy, enable&#x2026;. 当成个自定义bash理解就可以. 


# init.rc具体内容分析

init.rc地址位于 system/core/rootdir/init.rc文件中. 内容还是比较多的， 大部分都在创建文件夹， 修改权限, 更改内核参数. 截取一些比较有意思的内容: 
	
	```sh
    // 定义了Zygote Service
    import /init.${ro.zygote}.rc
    
    on init
    	# stune我也不知道具体是干什么的, 跟cpu调用配置有关。后看
    	mkdir /dev/stune
    	mount cgroup none /dev/stune schedtune
    	mkdir /dev/stune/foreground
    	mkdir /dev/stune/background
    	mkdir /dev/stune/top-app
    	mkdir /dev/stune/rt
    
    	chmod 0664 /dev/stune/tasks
    	chmod 0664 /dev/stune/foreground/tasks
    	chmod 0664 /dev/stune/background/tasks
    	chmod 0664 /dev/stune/top-app/tasks
    	chmod 0664 /dev/stune/rt/tasks
	```

其中 init.zygote64.rc如下:	
	```sh
    service zygote /system/bin/app_process64 -Xzygote /system/bin --zygote --start-system-server
    	class main
    	priority -20
    	user root
    	group root readproc
    	# 启动了一个zygote的unitx socket
    	socket zygote stream 660 root system
    	onrestart write /sys/android_power/request_state wake
    	onrestart write /sys/power/state on
    	onrestart restart audioserver
    	onrestart restart cameraserver
    	onrestart restart media
    	onrestart restart netd
    	onrestart restart wificond
    	writepid /dev/cpuset/foreground/tasks
	```
zygote的实现为java, 为frameworks/base/core/java/com/android/internal/os/Zygote.java, 具体分析见下篇博客. 

init.rc中包含了几个action, early-init, init, late-init这几个动作由init程序自身触发， 其他action比如 post-fs由init.rc tigger 指令触发. 

# native service种类

具体有哪些native service并没有在源码的init.rc文件中直接编写，而是由各自的Android.mk通过编译生成的. 由mk构建工具的LOCAL\_INIT\_RC(Android.bp的 init\_rc)属性指定. 例如logcatd.rc
	```sh
    # logcatd service
    service logcatd /system/bin/logcatd -L -b ${logd.logpersistd.buffer:-all} -v threadtime -v usec -v printable -D -f /data/misc/logd/logcat -r 1024 -n ${logd.logpersistd.size:-256} --id=${ro.build.id}
    	class late_start
    	disabled
    	# logd for write to /data/misc/logd, log group for read from log daemon
    	user logd
    	group log
    	writepid /dev/cpuset/system-background/tasks
    	oom_score_adjust -600
	```

几个有趣的native service(通过grep全局搜出来的)

-   service\_manager.rc: service manager服务
-   netd.rc: 网络服务(service netd)
-   vold.rc: vold进程, 这个不是window中的void进程，而是Volume Daemon进程, 是用来管理控制Android平台的外部存储设备的
-   logcatd.rc: logcat服务
-   cameraserver.rc: 照相机camera服务
-   mediaserver.rc: 多媒体服务
-   audioserver.rc: 音频服务
-   surfaceflinger.rc: 显示合成服务
-   wifi-events.rc: wifi相关
-   installd.rc: 用于安装apk文件的服务
-   dumpstate.rc: 命令行中dump使用的服务
