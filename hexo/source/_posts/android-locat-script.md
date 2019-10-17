---
title: android logcat 过滤脚本
date: 2019-10-17 15:51:23
tags: [python, android, logcat]
---
Android Log 系统将日志分为了radio, events, main, system, crash, all, default(main, system, crash)这几个缓冲区， 由于默认不会显示events， 但是阅读framework源码时会发现会有很多日志是通过EventLog中的方法写到events缓冲区中的. 提供一个脚本用于格式化输出logcat的events日志. 
<!-- more  -->

# 特色与动力

-   **VS AndroidStudio:** 可以跟踪events与systemLog缓冲区
-   **VS Logcat:** 基于Logcat命令, 更强的筛选功能与高亮输出
-   简单的python脚本， 理论上MAC, Linux, Window均可使用(window未经测试)

另外:
这个脚本功能很少, 是跟另一个开源项目的一部分, 具体代码会在这里粘出。 至于源代码可能需要读者从源代码中查找了. 


# 使用例子

例如想要跟踪ActivityManagerService的活动流程, 
	```py
    from adb import adbutil
    
    if __name__ == '__main__':
    	adbutil.adb_filter(lambda pid, tid, tag, content: tag.startswith('am_'))
	```

输出的结果类似如下:

    02-09 14:23:39.660  5103  5103 I am_on_resume_called: [0,com.android.launcher3.Launcher,RESUME_ACTIVITY]
    02-09 14:23:45.394  3466  3584 I am_pause_activity: [0,86858442,com.cyanogenmod.trebuchet/com.android.launcher3.Launcher]
    02-09 14:23:45.396  5103  5103 I am_on_paused_called: [0,com.android.launcher3.Launcher,handlePauseActivity]
    02-09 14:23:45.435  3466  3575 I am_stop_activity: [0,86858442,com.cyanogenmod.trebuchet/com.android.launcher3.Launcher]
    02-09 14:23:45.439  5103  5103 I am_on_stop_called: [0,com.android.launcher3.Launcher,sleeping]

如果是在shell中观看的话, 会有颜色高亮. 

从例子中， 可以看出提供了根据pid， tid， tag， content进行筛选的能力


# 源代码

原理很简单， 就是调用logcat命令， 截取输出， 分析而已

	```py
    def log_highlight(level, line):
    	level_color = {
    		"I": colored.cyan,
    		"V": colored.black,
    		"D": colored.green,
    		"W": colored.yellow,
    		"E": colored.red
    	}
    	puts(level_color[level](line), newline=False)
    
    
    def adb_filter(filter, buffer='events'):
    	shell = subprocess.Popen(['adb', 'shell', 'logcat', '-b', buffer], stdout=subprocess.PIPE)
    	try:
    		while True:
    			line = shell.stdout.readline()
    			if line != b'':
    				line = str(line, 'utf-8')
    				items = re.split(r' +', line, 6)
    				pid = items[2]
    				tid = items[3]
    				level = items[4]
    				tag = items[5]
    				content = items[6]
    				if filter(pid, tid, tag, content):
    					fileparsers.log_highlight(level, line)
    			else:
    				print('捕捉到空')
    				break
    	except KeyboardInterrupt:
    		print('退出adb shell')
	```

