---
title: Socket timeout时间代表的含义
date: 2019-11-13 18:34:55
tags: [socket, linux, android, java]
---

遇到一个关于timeout的bug, 发现自己不能准确解释清楚readtimeout, writetimeout, connecttimeout具体表示的含义, 这里扒拉下源码研究下(Android平台)

<!-- more  -->

# 定位各个timeout位置

定位到使用readTimeout与connectTimeout的位置: 
	```java
    // 位于OkHttp的SocketConnector.java
    // soTimeout赋值为readTimeout
      private Socket connectRawSocket(int soTimeout, int connectTimeout, Route route)
    	  throws RouteException {
    	Platform platform = Platform.get();
    	try {
    	  Proxy proxy = route.getProxy();
    	  Address address = route.getAddress();
    	  Socket socket;
    	  if (proxy.type() == Proxy.Type.DIRECT || proxy.type() == Proxy.Type.HTTP) {
    		socket = address.getSocketFactory().createSocket();
    	  } else {
    		socket = new Socket(proxy);
    	  }
    	  socket.setSoTimeout(soTimeout);
    	  platform.connectSocket(socket, route.getSocketAddress(), connectTimeout);
    
    	  return socket;
    	} catch (IOException e) {
    	  throw new RouteException(e);
    	}
      }
	```
可以发现soTimeout(即readTimeout)直接传递各类socket的setSoTimeout. 根据其文档: 设置一个有效的soTimeout后, 对这个socket的InputStream调用read方法时将之多阻塞设置的方法. 如果超时则抛出SocketTimeoutException(内部实现同样适用poll方式: libcore/ojluni/src/main/native/SocketInputStream.c). 

跟踪platform.connectSocket在Android平台中, 真实实现(java部分)如下: 
	``` java
    private static void connectErrno(FileDescriptor fd, InetAddress inetAddress, int port, int timeoutMs) throws ErrnoException, IOException {
    	// With no timeout, just call connect(2) directly.
    	if (timeoutMs <= 0) {
    		Libcore.os.connect(fd, inetAddress, port);
    		return;
    	}
    
    	// For connect with a timeout, we:
    	//   1. set the socket to non-blocking,
    	//   2. connect(2),
    	//   3. loop using poll(2) to decide whether we're connected, whether we should keep
    	//      waiting, or whether we've seen a permanent failure and should give up,
    	//   4. set the socket back to blocking.
    
    	// 1. set the socket to non-blocking.
    	IoUtils.setBlocking(fd, false);
    
    	// 2. call connect(2) non-blocking.
    	long finishTimeNanos = System.nanoTime() + TimeUnit.MILLISECONDS.toNanos(timeoutMs);
    	try {
    		Libcore.os.connect(fd, inetAddress, port);
    		IoUtils.setBlocking(fd, true); // 4. set the socket back to blocking.
    		return; // We connected immediately.
    	} catch (ErrnoException errnoException) {
    		if (errnoException.errno != EINPROGRESS) {
    			throw errnoException;
    		}
    		// EINPROGRESS means we should keep trying...
    	}
    
    	// 3. loop using poll(2).
    	int remainingTimeoutMs;
    	do {
    		remainingTimeoutMs =
    				(int) TimeUnit.NANOSECONDS.toMillis(finishTimeNanos - System.nanoTime());
    		if (remainingTimeoutMs <= 0) {
    			throw new SocketTimeoutException(connectDetail(fd, inetAddress, port, timeoutMs,
    					null));
    		}
    	} while (!IoBridge.isConnected(fd, inetAddress, port, timeoutMs, remainingTimeoutMs));
    	IoUtils.setBlocking(fd, true); // 4. set the socket back to blocking.
    }
    
    
    public static boolean isConnected(FileDescriptor fd, InetAddress inetAddress, int port, int timeoutMs, int remainingTimeoutMs) throws IOException {
    	ErrnoException cause;
    	try {
    		StructPollfd[] pollFds = new StructPollfd[] { new StructPollfd() };
    		pollFds[0].fd = fd;
    		pollFds[0].events = (short) POLLOUT;
    		int rc = Libcore.os.poll(pollFds, remainingTimeoutMs);
    		if (rc == 0) {
    			return false; // Timeout.
    		}
    		int connectError = Libcore.os.getsockoptInt(fd, SOL_SOCKET, SO_ERROR);
    		if (connectError == 0) {
    			return true; // Success!
    		}
    		throw new ErrnoException("isConnected", connectError); // The connect(2) failed.
    	} catch (ErrnoException errnoException) {
    		if (!fd.valid()) {
    			throw new SocketException("Socket closed");
    		}
    		cause = errnoException;
    	}
    	String detail = connectDetail(fd, inetAddress, port, timeoutMs, cause);
    	if (cause.errno == ETIMEDOUT) {
    		throw new SocketTimeoutException(detail, cause);
    	}
    	throw new ConnectException(detail, cause);
    }
	```
可以发现connecttimeout的实现原理是将socket转化为non-block模式， 然后调用系统调用poll等待一定的事件. 

OKHttp的writeTimeout是给okio.AsyncTimeout使用的: 
	```java
    public final void enter() {
      if (inQueue) throw new IllegalStateException("Unbalanced enter/exit");
      long timeoutNanos = timeoutNanos();
      boolean hasDeadline = hasDeadline();
      if (timeoutNanos == 0 && !hasDeadline) {
    	return; // No timeout and no deadline? Don't bother with the queue.
      }
      inQueue = true;
      // schedule这里实现特别low， 就是启动了一个线程
      scheduleTimeout(this, timeoutNanos, hasDeadline);
    }
	```
其中Okio中提示了具体用法:
	```java
    // okio.Okio.java
    private static AsyncTimeout timeout(final Socket socket) {
      return new AsyncTimeout() {
    	@Override protected IOException newTimeoutException(IOException cause) {
    	  InterruptedIOException ioe = new SocketTimeoutException("timeout");
    	  if (cause != null) {
    		ioe.initCause(cause);
    	  }
    	  return ioe;
    	}
    
    	@Override protected void timedOut() {
    	  try {
    		socket.close();
    	  } catch (Exception e) {
    		logger.log(Level.WARNING, "Failed to close timed out socket " + socket, e);
    	  }
    	}
      };
    }
	```
可以发现writeTimeout由1. 每次write调用后判断执行时间, 2. 由子线程计时判断(到时见close socket)完成. 


# systemcall中的timeout

由于现在的TCP/IP栈由内核提供, 其能力也有系统调用限制. 首先看看关于socketopt能够设置哪些属性(man setsockopt). 

-   SO\_DEBUG: 启用debug信息记录
-   SO\_REUSEADDR: 本地地址复用开启
-   SO\_REUSEPORT: 允许地址与端口被重复bind(一般用于区分TCP/UDP)
-   SO\_KEEPALIVE: 启用保持连接长活功能
-   SO\_DONTROUTE: 绕过路由器
-   SO\_SNDBUF: 设置发送缓存大小
-   SO\_RCVBUF: 设置接受缓存大小
-   SO\_LINGER: 设置socket close时等待时间(等待缓存发送完成)
-   SO\_SNDLOWAT: 设置发送数据最小值
-   SO\_RCVLOWAT: 设置接受数据最小值
-   SO\_SNDTIMEO: 设置output的timeout值
-   SO\_RCVTIMEO: 设置input的timeout值

这里关注两个TIMEO时间, 看下原文: 

    SO_SNDTIMEO is an option to set a timeout value for output operations.  It accepts a struct timeval parameter
    with the number of seconds and microseconds used to limit waits for output operations to complete.  If a send
    operation has blocked for this much time, it returns with a partial count or with the error EWOULDBLOCK if no
    data were sent.  In the current implementation, this timer is restarted each time additional data are deliv-
    ered to the protocol, implying that the limit applies to output portions ranging in size from the low-water
    mark to the high-water mark for output.
    
    SO_RCVTIMEO is an option to set a timeout value for input operations.  It accepts a struct timeval parameter
    with the number of seconds and microseconds used to limit waits for input operations to complete.  In the
    current implementation, this timer is restarted each time additional data are received by the protocol, and
    thus the limit is in effect an inactivity timer.  If a receive operation has been blocked for this much time
    without receiving additional data, it returns with a short count or with the error EWOULDBLOCK if no data
    were received.  The struct timeval parameter must represent a positive time interval; otherwise, setsockopt()
    returns with the error EDOM.

可以判定系统底层的socket是同时支持recv与send的timeout的. 看一下Java层支持的属性(libcore/luni/src/main/java/libcore/io/IoBridge.java): 
	```java
    // 对Java层支持的Option转换到native(名字看SO_XXX的就好)
    private static void setSocketOptionErrno(FileDescriptor fd, int option, Object value) throws ErrnoException, SocketException {
    	switch (option) {
    	case SocketOptions.SO_BROADCAST:
    		Libcore.os.setsockoptInt(fd, SOL_SOCKET, SO_BROADCAST, booleanToInt((Boolean) value));
    		return;
    	case SocketOptions.SO_KEEPALIVE:
    		Libcore.os.setsockoptInt(fd, SOL_SOCKET, SO_KEEPALIVE, booleanToInt((Boolean) value));
    		return;
    	case SocketOptions.SO_LINGER:
    		boolean on = false;
    		int seconds = 0;
    		if (value instanceof Integer) {
    			on = true;
    			seconds = Math.min((Integer) value, 65535);
    		}
    		StructLinger linger = new StructLinger(booleanToInt(on), seconds);
    		Libcore.os.setsockoptLinger(fd, SOL_SOCKET, SO_LINGER, linger);
    		return;
    	case SocketOptions.SO_OOBINLINE:
    		Libcore.os.setsockoptInt(fd, SOL_SOCKET, SO_OOBINLINE, booleanToInt((Boolean) value));
    		return;
    	case SocketOptions.SO_RCVBUF:
    		Libcore.os.setsockoptInt(fd, SOL_SOCKET, SO_RCVBUF, (Integer) value);
    		return;
    	case SocketOptions.SO_REUSEADDR:
    		Libcore.os.setsockoptInt(fd, SOL_SOCKET, SO_REUSEADDR, booleanToInt((Boolean) value));
    		return;
    	case SocketOptions.SO_SNDBUF:
    		Libcore.os.setsockoptInt(fd, SOL_SOCKET, SO_SNDBUF, (Integer) value);
    		return;
    	case SocketOptions.SO_TIMEOUT:
    		int millis = (Integer) value;
    		StructTimeval tv = StructTimeval.fromMillis(millis);
    		Libcore.os.setsockoptTimeval(fd, SOL_SOCKET, SO_RCVTIMEO, tv);
    		return;
    }
	```
可以发现Java层是支持SO\_RCVTIMEO的, 但是SO\_SNDTIMEO被Java吃了, 不再支持, 实际上Java层不再支持SO\_SNDTIMEO可能是 "SNDTIMEO的值与我们理解的有很大出入":

简单介绍下TCP包传输流程: 可以将通信的双发理解成寄件人与收件人, 与他们打交道的分别是寄件人的邮箱, 收件人的邮箱. SNDTIMEO的时间限制的是寄件人将邮件放进寄件人邮箱的时间, 并不是邮件到达收件人的时间. 寄件人邮箱是有缓存的, 一般都会立即返回OK的. 所以此值的应用范围并不大, OKHttp才会封装一个writeTimeOut来作为单独的writeTimeOut. 

比较有意思的是BSD的man手册和linux的man手册在send函数的说明中有细微的差别(Linux的更加易懂一点): 

    #BSD:
    	 No indication of failure to deliver is implicit in a send().  Locally detected errors are indicated by a return value of -1.
    
    #Linux:
    	 Successful completion of a call to send() does not guarantee delivery of the message. A return value of -1 indicates only locally-detected errors.

由于send函数仅仅是将数据发送到内核, 那close做了什么. 如果设置了SO\_LINGER时间，则等待最多SO\_LINGER时间发送缓存完成, 否则立即返回， 缺省立即返回. 

SO\_SNDBUF的默认值位于/proc/sys/net/core/wmem\_default, 允许的最大值是/proc/sys/net/core/wmem\_max, 最小值是4K(system page size). 在笔者的OnePlus 6T中默认值是229376(224KB), 最大值是8388608(8192KB).

SO\_SNDBUF理论上是不应该小鱼带宽和延迟的乘积, 自Linux 2.4开始, TCP会根据内存情况自动调整SNDBUF的值(介于最大值， 最小值之间). 
