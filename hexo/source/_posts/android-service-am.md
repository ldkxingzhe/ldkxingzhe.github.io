---
title: android-service-am
date: 2019-10-18 20:04:31
tags: [android, am]
---
am Android系统的活动管理器, 系统使用AM service管理应用的四大组件, 是Android系统的大管家. 弄明白大管家的工作机制， 方便我们与其打交道. 在阐述工作原理的同时，提供一些工具的使用. 
<!--  more -->
# 前言

ActivityManagerService是一个很庞大的模块, 接口相对简单很多， 通过IActivityManager.aidl的接口定义弄明白对外提供了哪些服务(我们关心的服务, 关心的话可以自行搜索): 

<table border="2" cellspacing="0" cellpadding="6" rules="groups" frame="hsides">


<colgroup>
<col  class="org-left" />

<col  class="org-left" />

<col  class="org-left" />

<col  class="org-left" />
</colgroup>
<tbody>
<tr>
<td class="org-left">操控对象</td>
<td class="org-left">相关函数</td>
<td class="org-left">调用者</td>
<td class="org-left">作用</td>
</tr>


<tr>
<td class="org-left">activity</td>
<td class="org-left">startActivity</td>
<td class="org-left">Instrumentation.startActivity</td>
<td class="org-left">启动Activity</td>
</tr>


<tr>
<td class="org-left">&#xa0;</td>
<td class="org-left">finishActivity</td>
<td class="org-left">由Activity的finish调用</td>
<td class="org-left">finishActivity</td>
</tr>


<tr>
<td class="org-left">&#xa0;</td>
<td class="org-left">activityIdle</td>
<td class="org-left">有ActivityThread添加IdleHandler触发</td>
<td class="org-left">&#xa0;</td>
</tr>


<tr>
<td class="org-left">&#xa0;</td>
<td class="org-left">activityPaused/Stoped</td>
<td class="org-left">由ActivityThread在performActivityPaused后调用</td>
<td class="org-left">&#xa0;</td>
</tr>


<tr>
<td class="org-left">application</td>
<td class="org-left">handleApplicationCrash</td>
<td class="org-left">RuntimeInit.java 的KillApplicationHandler</td>
<td class="org-left">显示Crash对话框</td>
</tr>


<tr>
<td class="org-left">&#xa0;</td>
<td class="org-left">attachApplication</td>
<td class="org-left">由ActivityThread启动时调用</td>
<td class="org-left">表明ActivityThread准备就绪</td>
</tr>


<tr>
<td class="org-left">task</td>
<td class="org-left">moveTaskToFront</td>
<td class="org-left">ActivityManager调用</td>
<td class="org-left">&#xa0;</td>
</tr>


<tr>
<td class="org-left">&#xa0;</td>
<td class="org-left">moveTaskBackwards</td>
<td class="org-left">none</td>
<td class="org-left">&#xa0;</td>
</tr>


<tr>
<td class="org-left">&#xa0;</td>
<td class="org-left">getTaskForActivity</td>
<td class="org-left">Activity自身调用</td>
<td class="org-left">&#xa0;</td>
</tr>


<tr>
<td class="org-left">configuration</td>
<td class="org-left">updateConfiguration</td>
<td class="org-left">&#xa0;</td>
<td class="org-left">&#xa0;</td>
</tr>


<tr>
<td class="org-left">Alarm</td>
<td class="org-left">noteWakeupAlarm</td>
<td class="org-left">&#xa0;</td>
<td class="org-left">&#xa0;</td>
</tr>
</tbody>
</table>


# Activity相关的

跟Activity相关的任务是TaskRecord, ActivityStack, ActivityStackSupervisor这三个类, 其中ActivityStackSupervisor是Activity管理的大总管, 其直接管理的对象是多个地区经理ActivityStack. ActivityStack管理本地区的多个店长TaskRecord, 每个TaskRecord记录管理多个店员.  对了还有一个ActivityStarter, 这是一个HR， 用于招聘安置店员的. 

大总管只有一个， 是ActivityManagerService初始化时直接new出来的。 


## 地区经理ActivityStack

固定的地区经理ActivityStack

-   HOME\_STACK\_ID:                 0, Home activity stack ID
-   FULLSCREEN\_WORKSPACE\_STACK\_ID: 1, 全屏模式的Activity启动位置
-   FREEFORM\_WORKSPACE\_STACK\_ID:   2,
-   DOCKED\_STACK\_ID:               3,
-   PINNED\_STACK\_ID:               4, 这个是跟画中画有关的一个特性
-   RECENTS\_STACK\_ID:              5, 最近任务

能够构造地区经理ActivityStack的方法是ActivityStackSupervisor.createStackOnDisplay， 具体调用来源: 

-   ActivityManagerService.createStackOnDisplay: 
    -   通过调用adb shell am stack start <DISPLAY\_ID> <INTENT> 启动
-   ActivityStackSupervisor.getStack(stackId, createStaticStaticStackIfNeeded, createOnTop): 按需创建
    -   ActivityManagerService.positionTaskInStack(taskId, stackId, position)
    -   ActivityStackSupervisor.setWindowManager时会构造mHomeStack
    -   ActivityStackSupervisor.restoreRecentTaskLocked
    -   ActivityStackSupervisor.moveTopStackActivityToPinnedStackLocked      # pictureMode
    -   ActivityStarter.getLauchStack 获取启动Activity的所属Stack, 按需创建RECENT\_STACK\_ID, ASSISTANT\_STACK\_ID, 以及其他.

-   ActivityStackSupervisor.getValidLauchStackOnDisplay(displayId, r): 不是默认屏幕的话会按需创建一个


### adb命令查看当前的Stack信息

在手机刚启动完成后查看ActivityStack信息列表:

    $ adb shell am stack list
    Stack id=0 bounds=[0,0][1440,2560] displayId=0 userId=0
      taskId=1276: com.android.launcher3/com.android.launcher3.Launcher bounds=[0,0][1440,2560] userId=0 visible=true topActivity=ComponentInfo{com.android.launcher3/com.android.launcher3.Launcher}

可以看到0是Home Stack ID

打开一个App后

    $ adb shell am stack list
    Stack id=1 bounds=[0,0][1440,2560] displayId=0 userId=0
      taskId=1277: com.android.messaging/com.android.messaging.ui.conversationlist.ConversationListActivity bounds=[0,0][1440,2560] userId=0 visible=true topActivity=ComponentInfo{com.android.messaging/com.android.messaging.ui.conversationlist.ConversationListActivity}
    
    Stack id=0 bounds=[0,0][1440,2560] displayId=0 userId=0
      taskId=1276: com.android.launcher3/com.android.launcher3.Launcher bounds=[0,0][1440,2560] userId=0 visible=false topActivity=ComponentInfo{com.android.launcher3/com.android.launcher3.Launcher}

退出这个App后Stack信息又变回了刚启动时的样子。 可以看出ActivityStack被及时销毁了. 

查看过近期任务列表后: 

    Stack id=0 bounds=[0,0][1440,2560] displayId=0 userId=0
      taskId=1276: com.android.launcher3/com.android.launcher3.Launcher bounds=[0,0][1440,2560] userId=0 visible=true topActivity=ComponentInfo{com.android.launcher3/com.android.launcher3.Launcher}
    
    Stack id=5 bounds=[0,0][1440,2560] displayId=0 userId=0
      taskId=1280: com.android.systemui/com.android.systemui.recents.RecentsActivity bounds=[0,0][1440,2560] userId=0 visible=false topActivity=ComponentInfo{com.android.systemui/com.android.systemui.recents.RecentsActivity}

可以看到id=5是最近任务列表Stack


### 关于地区ActivityStack一些问题解答

1.  ActivityStack与Display一一绑定， 可以换所属地区吗?

    答案是可以, mDisplayId这个属性可以重新赋值, 可以从显示器中removeFromDisplay, 然后postAddToDisplay即可完成地区的转移.  我们是可以在不同显示屏中拖拽页面的. 


## 店长TaskRecord(店员ActivityRecord)

店长TaskRecord是由地区经理ActivityStack的createTaskRecord创建的. 正常流程下, 由setTaskFromReuseOrCreateNewTask, setTaskToCurrentTopOrCreateNewTask调用, 均在ActivityStarter中. 

ActivityStarter这个HR一次只会招聘一个人, 在招聘过程中， 会根据需要协助创建店长TaskRecord. 创建TaskRecord的位置:

-   ActivityManagerService.addAppTask, 通过调用ActivityManager调用
-   TaskRecord restoreFromXml 用于重启后状态恢复
-   ActivityStack.createTaskRecord
    -   resetTargetTaskIfNeededLocked
    -   moveActivityToPinnedStackLocked 画中画有关的， 暂时忽略
    -   ActivityStarter.setTaskFromReuseOrCreateNewTask 由ActivityStarter.startActivityUnchecked 调用
    -   ActivityStarter.setTaskToCurrentTopOrCreateNewTask 由ActivityStarter.startActivityUnchecked调用

维护TaskRecord的关键函数是ActivityStarter.startActivityUnchecked(实际上也是招聘店员的过程). 流程图如下入: 
![img](https://ldk-blog.oss-cn-beijing.aliyuncs.com/blog/ActivityStarter.startActivityUnChecked.svg)

除了需要调用WM服务的ActivityStack.moveToFront, 在ActivityRecord构造完成，并计入TaskRecord后(可以理解为入职后)。 大总管ActivityStackSupervisor会通过 **resumeFocusedStackTopActivityLocked** 方法将对应的Activity推到前台显示， 直接操作当然是ActivityStack完成的. 动画Transaction是这个过程做的. 


## Activity的启动过程

通过源码阅读跟踪下Activity的启动过程, 先来张时序图:

![img](https://ldk-blog.oss-cn-beijing.aliyuncs.com/blog/Activity%E5%90%AF%E5%8A%A8%E6%B5%81%E7%A8%8B.png)

由于Activity的启动过程情况种类比较多,某些细节过于繁琐, 且整个调用过程存在多个异步调用, 这张时序图也仅仅包含了关键几个步骤， 可以参见这个时序图查看完整的代码. 

-   首先Instrumentation调用am服务的startActivityAsUser, 开始通知AM服务进入Activity启动过程
-   通过ActivityStarter调用startActivity, startActivityUnchecked主要用于计算flags，对应Stack, 对应Task
-   调用对应ActivityStack的startActivityLocked方法, 将ActivityRecord这条记录插入对应的Task中(也包括对应的WM服务)
-   调用ActivityStackSupervisor的resumeFocusedStackTopActivityLocked令新Actiivty进入resume状态

这里详细说下resumeFocusedStackTopActivityLocked这个方法, 直白点说， 就是通知大总管ActivityStackSupervisor让最上层的那个Activity可见且保证进入resume状态, 接下来对应的ActivityStack作为地区经理需要做一下动作：

-   步骤1: 令上一个resume的Activity pause. 知道全部Activity pause完成(不一定)才允许接着往下走
-   pause完成后通过AMS会调用ActivityStack的completePauseLocked， 调用了resumeFocusedStackTopActivityLocked
-   由于pause完成, 会跳过步骤1, 如果可以直接resume， 则这几resume 否则会调用ActivityStackSupervisor的startSpecificActivityLocked
-   若进程存活则调用realStartActivity, 若进程不存活, 则调用startProcess启动进程，进程启动后会调用attachApplication，然后调用realStartActivity
-   realStartActivity中会调用scheduleLaunchActivity


# Activity的销毁与恢复

销毁Activity会(不是绝对)调用destory, 对于AM而言只有一个地方调用了。 那就是ActivityStack.java的destroyActivityLocked方法

销毁两种情况: 自己调用了finish方法， 或者系统由于某些原因对activity进行了回收. ActivityThread在调用onDestroy后会调用AM的onDestroyed的方法更新状态. 而在onDestroyed中， 如果此Activity finished则从历史中(实际上就是记录在TaskRecord中)删除, 否则保留. 

针对第二种情况， 保留Activity， 是如何发生的: 1. 调用了activity的releaseInstance方法. 第二种是在内存低的时候调用的: 
ActivityThread.java中的看门狗:

    // Watch for getting close to heap limit.
    BinderInternal.addGcWatcher(new Runnable() {
    	@Override public void run() {
    		if (!mSomeActivitiesChanged) {
    			return;
    		}
    		Runtime runtime = Runtime.getRuntime();
    		long dalvikMax = runtime.maxMemory();
    		long dalvikUsed = runtime.totalMemory() - runtime.freeMemory();
    		if (dalvikUsed > ((3*dalvikMax)/4)) {
    			if (DEBUG_MEMORY_TRIM) Slog.d(TAG, "Dalvik max=" + (dalvikMax/1024)
    					+ " total=" + (runtime.totalMemory()/1024)
    					+ " used=" + (dalvikUsed/1024));
    			mSomeActivitiesChanged = false;
    			try {
    				mgr.releaseSomeActivities(mAppThread);
    			} catch (RemoteException e) {
    				throw e.rethrowFromSystemServer();
    			}
    		}
    	}
    });

ActivityManagerService.java

    @Override
    public void releaseSomeActivities(IApplicationThread appInt) {
    	synchronized(this) {
    		final long origId = Binder.clearCallingIdentity();
    		try {
    			ProcessRecord app = getRecordForAppLocked(appInt);
    			mStackSupervisor.releaseSomeActivitiesLocked(app, "low-mem");
    		} finally {
    			Binder.restoreCallingIdentity(origId);
    		}
    	}
    }

然后进入ActivitySupervisor中, 如果同时存在两个以上的task才会被回收一个, 最后调用了ActivityStack的releaseSomeActivities


## 已销毁的Activity如何恢复

在后一个Activity调用finish时，会首先调用其onPause方法, 随后(或者超时)时调用ActivityStack的ensureActivitiesVisibleLocked方法, 然后调用makeVisibleAndRestartIfNeeded代理给StackSupervisor的startSpecificActivityLocked方法发出launch指令


## 已销毁的Activity的onActivityResult何时调用的

文档中说onActivityResult会在onResume之前调用, 所以判断会在onCreate与onResume之间调用才会有意义. 结合上一节中最后发出了launch指令触发了ActivityThread的handleLaunchActivity。在从Activity下手， 查找调用onActivityResult的地方dispatchActivityResult， 

最终找到结论: 在performResumeActivity中调用, 

    if (r.pendingResults != null) {
    	deliverResults(r, r.pendingResults);
    	r.pendingResults = null;
    }
    r.activity.performResume();


# Broadcast相关的

Android有个臭名昭著的全家桶互相唤醒功能， 对Android的内存与电量是一个很大的浪费。 再次阅读AM服务， 学习广播的发送接收过程。 

力求对AM服务进行改写， 彻底拦截黑名单中的广播滥用. 


## 广播的发送

发送广播为Context.sendBroadcast其实现为ContextImpl.java: 

    @Override
    public void sendBroadcast(Intent intent) {
    	warnIfCallingFromSystemProcess();
    	String resolvedType = intent.resolveTypeIfNeeded(getContentResolver());
    	try {
    		intent.prepareToLeaveProcess(this);
    		ActivityManager.getService().broadcastIntent(
    				mMainThread.getApplicationThread(), intent, resolvedType, null,
    				Activity.RESULT_OK, null, null, null, AppOpsManager.OP_NONE, null, false, false,
    				getUserId());
    	} catch (RemoteException e) {
    		throw e.rethrowFromSystemServer();
    	}
    }

可以看出最终调用了ActivityManagerService的broadcastIntent. 最终调用broadcastIntentLocked将Broadcast记录存放在Queue中. 


## 广播的分发

在广播的发送中， 广播记录最终被记录在了mFgBroadcastQueue和mBgBroadcastQueue中. 

