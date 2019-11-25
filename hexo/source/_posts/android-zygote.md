---
title: android zygote进程源码阅读
date: 2019-11-13 19:36:02
tags: [android, zygote]
---

zygote是Android开启Java世界的入口, 由init程序启动。Android中所有的应用进程(系统启动的)均由zygote启动. 
<!-- more  -->

# 控制权的转移, Java世界的开启

代码位于frameworks/base/cmds/app\_process/app\_main.cpp
	```cpp
    int main(int argc, char* const argv[])
    {   
    	// .... 
    	if (zygote) {
    		// 以zygote模式启动, 启动类为ZygoteInit
    		runtime.start("com.android.internal.os.ZygoteInit", args, zygote);
    	} else if (className) {
    		runtime.start("com.android.internal.os.RuntimeInit", args, zygote);
    	} else {
    		fprintf(stderr, "Error: no class name or --zygote supplied.\n");
    		app_usage();
    		LOG_ALWAYS_FATAL("app_process: no class name or --zygote supplied.");
    	}
    }
	```
至此, Android中的主要控制权转移给了java, 看看启动代码, frameworks/base/core/java/com/android/internal/os/ZygoteInit.java:
	```java
    public static void main(String argv[]) {
    	ZygoteServer zygoteServer = new ZygoteServer();
    	ZygoteHooks.startZygoteNoThreadCreation();
    
    	// Zygote goes into its own process group.
    	try {
    		Os.setpgid(0, 0);
    	} catch (ErrnoException ex) {
    		throw new RuntimeException("Failed to setpgid(0,0)", ex);
    	}
    
    	final Runnable caller;
    	try {
    		// Report Zygote start time to tron unless it is a runtime restart
    		if (!"1".equals(SystemProperties.get("sys.boot_completed"))) {
    			MetricsLogger.histogram(null, "boot_zygote_init",
    					(int) SystemClock.elapsedRealtime());
    		}
    
    		String bootTimeTag = Process.is64Bit() ? "Zygote64Timing" : "Zygote32Timing";
    		TimingsTraceLog bootTimingsTraceLog = new TimingsTraceLog(bootTimeTag,
    				Trace.TRACE_TAG_DALVIK);
    		bootTimingsTraceLog.traceBegin("ZygoteInit");
    		RuntimeInit.enableDdms();
    
    		boolean startSystemServer = false;
    		String socketName = "zygote";
    		String abiList = null;
    		boolean enableLazyPreload = false;
    		// 读取已知参数
    		for (int i = 1; i < argv.length; i++) {
    			if ("start-system-server".equals(argv[i])) {
    				startSystemServer = true;
    			} else if ("--enable-lazy-preload".equals(argv[i])) {
    				enableLazyPreload = true;
    			} else if (argv[i].startsWith(ABI_LIST_ARG)) {
    				abiList = argv[i].substring(ABI_LIST_ARG.length());
    			} else if (argv[i].startsWith(SOCKET_NAME_ARG)) {
    				socketName = argv[i].substring(SOCKET_NAME_ARG.length());
    			} else {
    				throw new RuntimeException("Unknown command line argument: " + argv[i]);
    			}
    		}
    
    		if (abiList == null) {
    			throw new RuntimeException("No ABI list supplied.");
    		}
    		// 获取init程序启动zygote服务时创建的socket
    		zygoteServer.registerServerSocket(socketName);
    		// In some configurations, we avoid preloading resources and classes eagerly.
    		// In such cases, we will preload things prior to our first fork.
    		if (!enableLazyPreload) {
    			bootTimingsTraceLog.traceBegin("ZygotePreload");
    			EventLog.writeEvent(LOG_BOOT_PROGRESS_PRELOAD_START,
    				SystemClock.uptimeMillis());
    			preload(bootTimingsTraceLog);
    			EventLog.writeEvent(LOG_BOOT_PROGRESS_PRELOAD_END,
    				SystemClock.uptimeMillis());
    			bootTimingsTraceLog.traceEnd(); // ZygotePreload
    		} else {
    			Zygote.resetNicePriority();
    		}
    
    		// Do an initial gc to clean up after startup
    		bootTimingsTraceLog.traceBegin("PostZygoteInitGC");
    		gcAndFinalize();
    		bootTimingsTraceLog.traceEnd(); // PostZygoteInitGC
    
    		bootTimingsTraceLog.traceEnd(); // ZygoteInit
    		// Disable tracing so that forked processes do not inherit stale tracing tags from
    		// Zygote.
    		Trace.setTracingEnabled(false, 0);
    
    		// Zygote process unmounts root storage spaces.
    		Zygote.nativeUnmountStorageOnInit();
    
    		// Set seccomp policy
    		Seccomp.setPolicy();
    
    		ZygoteHooks.stopZygoteNoThreadCreation();
    
    		if (startSystemServer) {
    			// 如果声明需要启动SystemServer, 则启动fork一个进程SystemServer
    			Runnable r = forkSystemServer(abiList, socketName, zygoteServer);
    
    			// {@code r == null} in the parent (zygote) process, and {@code r != null} in the
    			// child (system_server) process.
    			if (r != null) {
    				r.run();
    				return;
    			}
    		}
    
    		Log.i(TAG, "Accepting command socket connections");
    
    		// The select loop returns early in the child process after a fork and
    		// loops forever in the zygote.
    		caller = zygoteServer.runSelectLoop(abiList);
    	} catch (Throwable ex) {
    		Log.e(TAG, "System zygote died with exception", ex);
    		throw ex;
    	} finally {
    		zygoteServer.closeServerSocket();
    	}
    
    	// We're in the child process and have exited the select loop. Proceed to execute the
    	// command.
    	if (caller != null) {
    		caller.run();
    	}
    }
	```
大致流程描述如下: 

-   1. 读取已知参数, 比如是否启动system server.
-   2. 从环境变量中获取zygote这个socket.
-   3. fork出systemserver.
-   4. 监听socket, 等待执行应用程序的指令
-   5. 收到指令后, fork出应用程序的进程执行(ActivityThread.main). 原有进程继续步骤4.


# socket具体通信协议

当socket通信连接后, 具体通信处理由ZygoteConnection.processOneCommand定义: 
	```java
    // frameworks/base/core/java/com/android/internal/os/ZygoteConnection.java
    Runnable processOneCommand(ZygoteServer zygoteServer) {
    		String args[];
    		Arguments parsedArgs = null;
    		FileDescriptor[] descriptors;
    
    		try {
    			// 多个参数利用换行符切换, 第一行表示参数个数
    			args = readArgumentList();
    			descriptors = mSocket.getAncillaryFileDescriptors();
    		} catch (IOException ex) {
    			throw new IllegalStateException("IOException on command socket", ex);
    		}
    
    		// readArgumentList returns null only when it has reached EOF with no available
    		// data to read. This will only happen when the remote socket has disconnected.
    		if (args == null) {
    			isEof = true;
    			return null;
    		}
    
    		int pid = -1;
    		FileDescriptor childPipeFd = null;
    		FileDescriptor serverPipeFd = null;
    
    		parsedArgs = new Arguments(args);
    
    		// zygote进程本身会通过这个socket被下发一些加载指令. 
    		if (parsedArgs.abiListQuery) {
    			handleAbiListQuery();
    			return null;
    		}
    
    		if (parsedArgs.preloadDefault) {
    			handlePreload();
    			return null;
    		}
    
    		if (parsedArgs.preloadPackage != null) {
    			handlePreloadPackage(parsedArgs.preloadPackage, parsedArgs.preloadPackageLibs,
    					parsedArgs.preloadPackageCacheKey);
    			return null;
    		}
    
    		if (parsedArgs.permittedCapabilities != 0 || parsedArgs.effectiveCapabilities != 0) {
    			throw new ZygoteSecurityException("Client may not specify capabilities: " +
    					"permitted=0x" + Long.toHexString(parsedArgs.permittedCapabilities) +
    					", effective=0x" + Long.toHexString(parsedArgs.effectiveCapabilities));
    		}
    
    		applyUidSecurityPolicy(parsedArgs, peer);
    		applyInvokeWithSecurityPolicy(parsedArgs, peer);
    
    		applyDebuggerSystemProperty(parsedArgs);
    		applyInvokeWithSystemProperty(parsedArgs);
    
    		int[][] rlimits = null;
    
    		if (parsedArgs.rlimits != null) {
    			rlimits = parsedArgs.rlimits.toArray(intArray2d);
    		}
    
    		int[] fdsToIgnore = null;
    
    		if (parsedArgs.invokeWith != null) {
    			// 最后"$invokeWith app_process xxxx xxxx xxx"交给shell执行的. 
    			// 在AOSP中只可能是/system/bin/logwrapper app.info.nativeLibraryDir + '/wrap/sh'(定义在ActivityManagerService.java中)
    			try {
    				// 这个pipeFds主要用来互通进程号的管道
    				FileDescriptor[] pipeFds = Os.pipe2(O_CLOEXEC);
    				childPipeFd = pipeFds[1];
    				serverPipeFd = pipeFds[0];
    				Os.fcntlInt(childPipeFd, F_SETFD, 0);
    				fdsToIgnore = new int[]{childPipeFd.getInt$(), serverPipeFd.getInt$()};
    			} catch (ErrnoException errnoEx) {
    				throw new IllegalStateException("Unable to set up pipe for invoke-with", errnoEx);
    			}
    		}
    
    		/**
    		 * In order to avoid leaking descriptors to the Zygote child,
    		 * the native code must close the two Zygote socket descriptors
    		 * in the child process before it switches from Zygote-root to
    		 * the UID and privileges of the application being launched.
    		 *
    		 * In order to avoid "bad file descriptor" errors when the
    		 * two LocalSocket objects are closed, the Posix file
    		 * descriptors are released via a dup2() call which closes
    		 * the socket and substitutes an open descriptor to /dev/null.
    		 */
    
    		int [] fdsToClose = { -1, -1 };
    
    		FileDescriptor fd = mSocket.getFileDescriptor();
    
    		if (fd != null) {
    			fdsToClose[0] = fd.getInt$();
    		}
    
    		fd = zygoteServer.getServerSocketFileDescriptor();
    
    		if (fd != null) {
    			fdsToClose[1] = fd.getInt$();
    		}
    
    		fd = null;
    		// 这里fork出了一个进程
    		pid = Zygote.forkAndSpecialize(parsedArgs.uid, parsedArgs.gid, parsedArgs.gids,
    				parsedArgs.debugFlags, rlimits, parsedArgs.mountExternal, parsedArgs.seInfo,
    				parsedArgs.niceName, fdsToClose, fdsToIgnore, parsedArgs.instructionSet,
    				parsedArgs.appDataDir);
    
    		try {
    			if (pid == 0) {
    				// in child
    				zygoteServer.setForkChild();
    
    				zygoteServer.closeServerSocket();
    				IoUtils.closeQuietly(serverPipeFd);
    				serverPipeFd = null;
    
    				return handleChildProc(parsedArgs, descriptors, childPipeFd);
    			} else {
    				// In the parent. A pid < 0 indicates a failure and will be handled in
    				// handleParentProc.
    				IoUtils.closeQuietly(childPipeFd);
    				childPipeFd = null;
    				handleParentProc(pid, descriptors, serverPipeFd);
    				return null;
    			}
    		} finally {
    			IoUtils.closeQuietly(childPipeFd);
    			IoUtils.closeQuietly(serverPipeFd);
    		}
    	}
	```
连接这个socket的类时ZygoteProcess.java, 一般由ActivityManagerService触发. 


# systemserver的启动过程

正常的启动流程, ZygoteInit同样会fork出一个进程system\_process执行系列的java服务, 比如AM， PM， WM这一类的. 启动过程由ZygoteInit的forkSystemServer触发执行:
	```java
    private static Runnable forkSystemServer(String abiList, String socketName,
    		ZygoteServer zygoteServer) {
    	long capabilities = posixCapabilitiesAsBits(
    		OsConstants.CAP_IPC_LOCK,
    		OsConstants.CAP_KILL,
    		OsConstants.CAP_NET_ADMIN,
    		OsConstants.CAP_NET_BIND_SERVICE,
    		OsConstants.CAP_NET_BROADCAST,
    		OsConstants.CAP_NET_RAW,
    		OsConstants.CAP_SYS_MODULE,
    		OsConstants.CAP_SYS_NICE,
    		OsConstants.CAP_SYS_PTRACE,
    		OsConstants.CAP_SYS_TIME,
    		OsConstants.CAP_SYS_TTY_CONFIG,
    		OsConstants.CAP_WAKE_ALARM
    	);
    	/* Containers run without this capability, so avoid setting it in that case */
    	if (!SystemProperties.getBoolean(PROPERTY_RUNNING_IN_CONTAINER, false)) {
    		capabilities |= posixCapabilitiesAsBits(OsConstants.CAP_BLOCK_SUSPEND);
    	}
    	/* Hardcoded command line to start the system server */
    	String args[] = {
    		"--setuid=1000",
    		"--setgid=1000",
    		"--setgroups=1001,1002,1003,1004,1005,1006,1007,1008,1009,1010,1018,1021,1023,1032,3001,3002,3003,3006,3007,3009,3010",
    		"--capabilities=" + capabilities + "," + capabilities,
    		"--nice-name=system_server",
    		"--runtime-args",
    		"com.android.server.SystemServer",     // 这里定义了入口类与方法
    	};
    	ZygoteConnection.Arguments parsedArgs = null;
    
    	int pid;
    
    	try {
    		parsedArgs = new ZygoteConnection.Arguments(args);
    		ZygoteConnection.applyDebuggerSystemProperty(parsedArgs);
    		ZygoteConnection.applyInvokeWithSystemProperty(parsedArgs);
    
    		/* Request to fork the system server process */
    		pid = Zygote.forkSystemServer(
    				parsedArgs.uid, parsedArgs.gid,
    				parsedArgs.gids,
    				parsedArgs.debugFlags,
    				null,
    				parsedArgs.permittedCapabilities,
    				parsedArgs.effectiveCapabilities);
    	} catch (IllegalArgumentException ex) {
    		throw new RuntimeException(ex);
    	}
    
    	/* For child process */
    	if (pid == 0) {
    		if (hasSecondZygote(abiList)) {
    			waitForSecondaryZygote(socketName);
    		}
    
    		zygoteServer.closeServerSocket();
    		return handleSystemServerProcess(parsedArgs);
    	}
    
    	return null;
    }
	```
提供了SystemServer的入口类为: frameworks/base/services/java/com/android/server/SystemServer.java, 有整个system\_process进程的启动过程. 记录下感兴趣的几部分. 

createSystemContext:
	```java
    // SystemServer.java
    private void createSystemContext() {
    	ActivityThread activityThread = ActivityThread.systemMain();
    	mSystemContext = activityThread.getSystemContext();
    	mSystemContext.setTheme(DEFAULT_SYSTEM_THEME);
    
    	final Context systemUiContext = activityThread.getSystemUiContext();
    	systemUiContext.setTheme(DEFAULT_SYSTEM_THEME);
    }
    // ContextImpl.java 
    static ContextImpl createSystemContext(ActivityThread mainThread) {
    	// 默认值loadedApk, 包名信息为"android", resource资源也由专门的函数生成, 见AssetManager
    	LoadedApk packageInfo = new LoadedApk(mainThread); 
    	ContextImpl context = new ContextImpl(null, mainThread, packageInfo, null, null, null, 0,
    			null);
    	context.setResources(packageInfo.getResources());
    	context.mResources.updateConfiguration(context.mResourcesManager.getConfiguration(),
    			context.mResourcesManager.getDisplayMetrics());
    	return context;
    }
	```
service启动分类(系统服务太多了&#x2026;): 
	```java
    // Start services.
    try {
    	traceBeginAndSlog("StartServices");
    	startBootstrapServices();
    	startCoreServices();
    	startOtherServices();
    	SystemServerInitThreadPool.shutdown();
    } catch (Throwable ex) {
    	Slog.e("System", "******************************************");
    	Slog.e("System", "************ Failure starting system services", ex);
    	throw ex;
    } finally {
    	traceEnd();
    }
	```
