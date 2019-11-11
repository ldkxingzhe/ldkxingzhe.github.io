---
title: android 输入系统概述
date: 2019-11-04 17:22:38
tags: android, input
---


学习下Android的Input系统，哪些View可以显示输入法, 可以对输入法做哪些控制. 

<!-- more  -->

# EditText &#x2013; View如何配置可以显示输入框

Android的输入框控件是EditText, TextView是其父类, 一般情况下EditText可以被编辑, 而TextView不可以. 其区别在于方法getDefaultEditable的返回值, 在TextView的构造函数中发现getDefaultEditable用于控制是否创建mEditor对象, 然后两者就没有区别了. 
	```java
    private void createEditorIfNeeded(){
    	if(mEditor == null){
    		mEditor = new Editor(this);
    	}
    }
    
    // 用于校验View是否是一个文本输入框, true ---> 在这个View上显示一个软键盘输入框
    public boolean onCheckIsTextEditor() {
    	return mEditor != null && mEditor.mInputType != EditorInfo.TYPE_NULL;
    }
	```

由此可以发现onCreateInputConnection方法， 用于创建一个与输入法交互的通道InputConnection. 


# InputMethodManager &#x2013; 如何判定哪个View用于显示输入法

同样是电影的CS架构, InputMethodManager是一个单例模式, 运行在每个Client进程中, 与输入法IME的Service进程 进行通信。对应的远端Service是InputManagerService, 任意一个时间点仅支持一个InputConnection与IME有效通信。

InputMethodManager显示触发与View的focus有关, View通过onWindowFocusChanged, onFocusChanged, dispatchFinishTemporaryDetach, onAttachedToWindow回调触发InputMethodManager的focusIn方法. 然后scheduleCheckFocusLocked. 

-   scheduleCheckFocusLocked
-   ViewRootImpl.dispatchCheckFocus
-   延迟调用InputMethodManager的checkFocus方法
-   调用startInputInner方法显示键盘
    -   调用View.onCreateInputConnection创建InputConnection
    -   调用service的startInputOrWindowGainedFocus

另外InputMethodManager的onPostWindowFocus也可以调用focusInLocked方法, ViewGroup用于发现Focus的View的方式是View.findFocus. 


# InputMethodManagerService &#x2013; 输入法显示过程

InputMethodManagerService(一个标准的系统服务)是系统用来管理多个Input Methods的地方。 维持了一个mMethodList与mMethodMap用于记录各个输入法的信息。

输入法信息的读取是由InputMethodManagerService的buildInputMethodListLocked, 通过PackageManagerService服务查询action为"android.view.InputMethod"的所有服务, 并过滤掉没有android.permission.BIND\_INPUT\_METHOD权限的部分. buildInputMethodListLocked由一下位置调用: 

-   onActionLocaleChanged: 时区改变
-   onUnlockUser: 用户Unlock
-   switchUserLocked: 用户切换
-   setAdditionalInputMethodSubtypes
-   systemRunning: 系统启动阶段
-   onFinishPackageChanges: 安装包更新后

一般而言最常遇到的情况只有系统启动过程中, 和安装包更新后这两种情况, 符合咱们的猜测. 

HashMap mClients记录每个InputMethodManager(即客户端)的代理对象, 其更改由addClient与removeClient两个函数触发。 就添加而言: 

-   WindowManagerGlobal.getWindowSession会调用WindowManager.openSession 其参数client由InputMethodManager这个单例对象获取
-   WindowManagerService的openSession会初始化一个Session, 构造时会调用InputMethodManagerService.addClient添加新的Client对象

可以看到这里牵扯到了WindowManagerService的session, 不在本文中做过多介绍. 


## startInputOrWindowGainedFocus

分成两个函数: windowGainedFocus和startInput。 windowGainedFocus比startInput多的一步就是根据Window的flag判断计算动作。 

最后都会调用startInputUncheckedLocked进行显示处理, 流程如下图: 
![img](https://ldk-blog.oss-cn-beijing.aliyuncs.com/blog/IMS_startInputLocked.png)

总计一句话就是, 与旧InputMethodService解除绑定, WM中删除对应的View, 与新InputMethodServie绑定， WM添加新的View。


## InputBindResult: startInputOrWindowGainedFocus的返回值

由于是一个Parcelable的返回值， 其内包装了以下信息: 

-   IInputMethodSession method: 对应的InputMethodService接口
-   InputChannel channel: 一个发送消息的通道
-   String id:
-   int sequence:
-   int userActionNotificationSequenceNumber:

method这个IInputMethodSession由InputMethodManagerService.onSessionCreated触发构造, 实际上是由对应的InputMethodService触发的, 用于标记这三者统一状态的一个会话对象. 

channel: 一个发送消息的通道, 其构造触发之处是InputMethodManagerService.requestClientSessionLocked:
	```java
    void requestClientSessionLocked(ClientState cs) {
    	if (!cs.sessionRequested) {
    		if (DEBUG) Slog.v(TAG, "Creating new session for client " + cs);
    		InputChannel[] channels = InputChannel.openInputChannelPair(cs.toString());
    		cs.sessionRequested = true;
    		executeOrSendMessage(mCurMethod, mCaller.obtainMessageOOO(
    				MSG_CREATE_SESSION, mCurMethod, channels[1],
    				new MethodCallback(this, mCurMethod, channels[0])));
    	}
    }
	```

看着跟Unix的管道pipe有相似之处, 底层实现是一对UNIX socket, 代码位于frameworks/native/libs/input/InputTransport.cpp:

	```cpp
    status_t InputChannel::openInputChannelPair(const String8& name,
    		sp<InputChannel>& outServerChannel, sp<InputChannel>& outClientChannel) {
    	int sockets[2];
    	if (socketpair(AF_UNIX, SOCK_SEQPACKET, 0, sockets)) {
    		status_t result = -errno;
    		ALOGE("channel '%s' ~ Could not create socket pair.  errno=%d",
    				name.string(), errno);
    		outServerChannel.clear();
    		outClientChannel.clear();
    		return result;
    	}
    
    	int bufferSize = SOCKET_BUFFER_SIZE;
    	setsockopt(sockets[0], SOL_SOCKET, SO_SNDBUF, &bufferSize, sizeof(bufferSize));
    	setsockopt(sockets[0], SOL_SOCKET, SO_RCVBUF, &bufferSize, sizeof(bufferSize));
    	setsockopt(sockets[1], SOL_SOCKET, SO_SNDBUF, &bufferSize, sizeof(bufferSize));
    	setsockopt(sockets[1], SOL_SOCKET, SO_RCVBUF, &bufferSize, sizeof(bufferSize));
    
    	String8 serverChannelName = name;
    	serverChannelName.append(" (server)");
    	outServerChannel = new InputChannel(serverChannelName, sockets[0]);
    
    	String8 clientChannelName = name;
    	clientChannelName.append(" (client)");
    	outClientChannel = new InputChannel(clientChannelName, sockets[1]);
    	return OK;
    }
	```
	
另外追踪Channel的使用, Channel的用途是客户端进程将InputEvent发送给输入法引擎, 作用上与IInputMethodSession有些许重叠(有返回值, 哈哈)


# InputConnection通道与通信

回到InputMethodManager所在进程(即UI所在进程), View.onCreateInputConnection后， 这个InputConnection到底做了哪些事情. 其作为参数构建一个ControlledInputConnectionWrapper作为输入输出的上下文, 同样这个上下文对象也通过startInputOrWindowGainedFocus方法传给了InputMethodManagerService进程, 并记录为mCurInputContext, 当然最后会传递给对应的InputMethodService。 

InputConnection支持的动作由IInputContext.aidl定义: 

-   所有定义方法调用IInputConnectionWrapper方法都是异步的， 所以不会有返回值, 全是void
-   会代理给InputConnection的相应方法

所有InputConnection通信支持的协议内容可以参见InputConnection.java中的注释: 

-   getTextBeforeCursor(int n, int falgs): 获取当前光标前的文本内容
-   getTextAfterCursor(int n, int flags): 获取当前光标后的文本
-   getSelectedText(int flags): 获取选中的文本
-   getCursorCapsMode(int reqModes): 获取当前光标位置的capitalization mode
-   getExtractedText(ExtractedTextRequest request, int flags): 获取当前Editor中的内容， 并监听.
-   deleteSurroundingText(int beforeLength, int afterLength): 删除光标前后的字符串
-   setComposingText(CharSequence text, int newCursorPosition): 使用给定文本替换当前合成的文字, 并重设新的光标位置.
-   setComposingRegion(int start, int end):
-   finishComposingText():
-   commitText(CharSequence text, int newCursorPosition):
-   commitCompletion(CompletionInfo text):
-   commitCorrection(CorrectionInfo correctionInfo):
-   setSelection(int start, int end):
-   performEditorAction(int editorAction)
-   performContextMenuAction(int id)
-   beginBatchEdit()
-   endBatchEdit()
-   sendKeyEvent(KeyEvent event)
-   clearMetaKeyStates(int states)
-   performPrivateCommand(String action, Bundle data)
-   closeConnection()
-   commitContent

作为IME(InputMethod Engine)的开发者，要知道能调用哪些命令. 作为Editor开发者， 要知道需要处理哪些命令. 


## Editor


# CharSequence, Spanned等内部的文字表示

CharSequence更加像一个chat字符合集, 这个是Java本身提供的. Android中新加了Spanned接口作为拓展。 Spanned赋予了某个区间的文字attach对象的能力. Spnnable继承自Spanned， 赋予了添加与删除Span的能力. 然后就是Editable接口. 

对于任意一个Span, MARK表示在字符前， POINT表示在字符后. 通过MARK\_POINT flag 可以标价这个Span在其开头与结尾处插入字符时是否包含进入Span. (就是指定include, exclusive)

另外一个特殊的Spaned : COMPOSIING, 表示此块SPAN由输入法引擎操作， 是个临时的span， 额， 只有一个. 

Spaned有很多实现， 能够利用span绘制出很多特效， 不在这篇文章中占用太多篇幅。 后续会提供一个skia draw的文章. 
