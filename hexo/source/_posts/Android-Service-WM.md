---
title: Android Service之WindowManagerService
date: 2020-02-10 11:45:09
tags: ['Android', 'WindowManagerService', 'WM']
---

WM服务是Android的窗口管理器, 提供了多Window合成, 手势分发等服务. 

-   与相应的UI进程通过IWindowSession与IWindow接口通信
-   与SurfaceFlinger服务通过SurfaceSession通信, 并向UI进程暴露Surface用于绘制UI
<!--more-->

# 多窗口合成相关

-   WM内部维护了一个Session的ArraySet用于记录一系列活跃的, 与客户端通信的会话。
-   维护了一个已WindowToken为Key的， WindowState为Value的字典， 用于记录Window信息
-   维护了多个WindowState列表表示不同状态


## 基本概念


### Session是什么

Session代表一个有效的客户端会话，一个进程只有一个， 用于与WM通信交流。 

对对应的UI进程而言提供IWindowSession实现, 可跨进程传输. 由WindowManagerService的openSession方法触发构造, 在客户进程的触发条件是WindowManagerGLobal.getWindowSession. 

`由Session.addToDisplayXXX -> WindowManagerService.addWindow -> WindowState.attach -> Session.windowAddedLocked添加进入WM.sessions中， 客户端的触发函数是: ViewRootImpl.setView方法， 额， ViewRootImpl的Session引用通过WindowManagerGlobal.getWindowSession获取。`

对WM服务而言, 

-   内部属性mSurfaceSession: 用于与SurfaceFlinger ipc通信


### 通信流程

WM服务与相应的UI进程暴露了两个接口用于通信: IWindowSession和IWindow

-   第一步: 打开会话Session, 在UI进程WindowManagerService#openSession创建一个对应进程唯一的Session
-   第二步: 在UI进程(由ViewRootImpl的setView触发)中调用IWindowSession#add, addToDisplay等add方法将一个Window添加到WindowManagerService中
-   第三步: 在UI进程中, 若Window的属性发生改变, 调用IWindowSession#relayout告知WindowManagerService属性改变, 并且返回对应的Surface
-   第四步: WM服务通过IWindow接口告知Window, resize(窗口大小, 系统组件, 键盘等大小改变), moved(坐标改变), dispatchAppVisibility(应用可见性改变), dispatchGetNewSurface, WindowFocusChanged, closeSystemDialogs,


### AppWindowContainerControler

可以理解为暴露给ActivityManagerService的接口. 在AM服务(ActivityManagerService)中的ActivityRecord中调用创建AppWindowContainerControler, 也就是说Activity的IBinder token是由AM服务传递过来的, 用来构造WindowToken类. 


### WindowManagerService是如何记录Window信息的

在WM服务中, 使用WindowState对象记录Window的信息. 通过RootWindowContainer, DisplayContent, WindowState组成一个WindowState Tree:

-   RootWindowContainer: 由WindowManagerService持有, 其内部是多个DisplayContent
    -   DisplayContent: 表示一个显示屏, 其内部主要是DisplayChildWindowContainer. 
        -   DisplayChildWindowContainer: 包含多个TaskStack, 表示一系列的WindowState

1.  DisplayContent

    同样是一个WindowContainer， mChildren中放置的是DisplayChildWindowContainer. 
    
    -   mTaskStackContainers: 用于存放一个个StackTask
    -   mAboveAppWindowContainers: 与App无关的, 如StatusBar
    -   mBelowAppWindowContainers: 与App无关的, 如壁纸
    -   mImeiWindowContainers: 输入框
    -   mLayerController: WindowLayersController
    
    perrformLayout:
    
    -   调用WindowManagerPolicy的beginLayoutLw, 实现为PhoneWindowManager
    -   首先forAllWindows遍历所有的未attached的Window
    -   然后forAllWindows遍历所有attached的windows
    
    对所有window进行Layout时， 均会调用WindowManagerPolicy的layoutWindowLw方法
    
    applaySurfaceChangesTransaction:
    
    -   放置壁纸
    -   调用自身的performLayout计算各个Window的位置信息
    -   自上而下调用mApplySurfaceChangesTtransaction

2.  WindowState

    在WindowManager中记录一个Window的所有属性, 
    
    包含以下属性: 
    
    -   mSession: Session: 这个Session每个进程有一个
    -   mClient: IWindow: 对应的Window的Binder接口
    -   mToken: WindowTtoken
    -   mAppToken: AppWindowToken, 如果是一个app窗口， 则mAppToken与mToken相同
    -   mIsChildWindow
    -   mBaseLayer, mSubLayer
    -   mLayoutAttached, mIsImWindow, mIsWallpaper, mIsFloatingLayer
    -   mViewVisibility, mSystemUiVisibility, mAppOpVisibility
    -   mAppFreezing, mHidden, mWallpaperVisible, mResizeMode
    -   mLayer, mHaveFrame, mObscured, mTurnOnScreen
    
    -   mContentInsets, mLastContentInsets
    -   mWinAnimator: WindowStateAnimator
    
    computeFrameLw:
    
    -   如果是将被替换, 动画退出状态 不计算
    -   判断inFullscreenContainer, 大部分情况下是true
    -   判断windowsAreFloating, 大部分情况下是false
    
    定义了多个Frame的定义:
	
    <table border="2" cellspacing="0" cellpadding="6" rules="groups" frame="hsides">
    <colgroup>
    <col  class="org-left" />
    <col  class="org-left" />
    </colgroup>
    <tbody>
    <tr>
    <td class="org-left">mFrame</td>
    <td class="org-left">应用看到的真实Frame大小, 位于屏幕坐标系中, 也是DecorView的大小</td>
    </tr>
    <tr>
    <td class="org-left">mContainingFrame</td>
    <td class="org-left">&#xa0;</td>
    </tr>
    <tr>
    <td class="org-left">mParentFrame</td>
    <td class="org-left">&#xa0;</td>
    </tr>
    <tr>
    <td class="org-left">mDisplayFrame</td>
    <td class="org-left">当前TaskStack所占屏幕区域, 大部分是否就是整个屏幕大小</td>
    </tr>
    <tr>
    <td class="org-left">mOverscanFrame</td>
    <td class="org-left">包含过扫描的屏幕部分, 一般针对电视而言</td>
    </tr>
    <tr>
    <td class="org-left">mStableFrame</td>
    <td class="org-left">无论状态栏与导航栏是否可见, 均不包含它，一般是一个定值</td>
    </tr>
    <tr>
    <td class="org-left">mDecorFrame</td>
    <td class="org-left">不包含状态栏与导航栏的区域, 在状态栏与导航栏可见时其值与mStableFrame相同</td>
    </tr>
    <tr>
    <td class="org-left">mContentFrame</td>
    <td class="org-left">等于mDecorFrame减去输入法占用的区域(注释错误), 表示App的内容区</td>
    </tr>
    <tr>
    <td class="org-left">mVisibleFrame</td>
    <td class="org-left">兼容旧版App使用， 一般与mContentFrame相同(注释错误), 表示mContentFrame减去输入法</td>
    </tr>
    <tr>
    <td class="org-left">mOutsetFrame</td>
    <td class="org-left">包含不想绘制图形衬边的Frame, 如果有衬边, 比mContentFrame大一圈</td>
    </tr>
    <tr>
    <td class="org-left">mInsetFrrame</td>
    <td class="org-left">这个跟multiwindow模式有关</td>
    </tr>
    </tbody>
    </table>

1.  WindowState接口
    
        -   int getOwningUid():  获取窗口的所属uid
        -   String getOwningPackage()
        -   void computeFrameLw(Rect parentFrame, Rect displayFrame, Rect overlayFrame, Rect contentFrame, Rect visibleFrame, Rect decorFrame, Rect stableFrame, Rect outsetFrame)
        -   Rect getFrameLw(): 获取window当前被window manager赋予的frame
        -   Point getShowPositionLw(): 当前window的位置
        -   Rect getDisplayFrameLw()


## 多窗口布局相关

布局策略由WindowManagerPolicy这个类提供布局抽象,　并且定义了WindowState, InputConsumer, StartingSurface, WindowManagerFuncs(用于回调WM服务), PointerEventListener. 其中WindowManagerPolicy在手机上的实现为PhoneWindowManager, 用于在手机屏幕上进行窗口合成, 需要留意的接口如下:

-   void beginLayoutLw: 开始布局当前屏幕
-   void getContentRectLw(Rect r): 用于返回当前屏幕中可用于App展示的位置
-   void layoutWindowLw(WindowState win, WindowState attached): 当前屏幕中的任意一个Window layout时需要调用此方法
-   int focusChanged(WindowState lastFocus, WindowState newFocus)


### PhoneWindowManager.java

    # 用来dump PhoneWindowManager的状态信息
    adb shell dumpsys window policy

有几个Frame概念需要了解

-   mOverscanScreenLeft, mOverscanScreenTop, mOverscanScreenWidth, mOverscanScreenHeight: 包含过扫描区域的空间, 一般在电视才有意义
-   mUnrestrictedScreenLeft(Top, Width, Height): 当前屏幕的可见区域, 不会包含过扫描区域. 一般与mOverrscanScreenXXX相同
-   mRestrictedOverscanScreenLeft(Top, Width, Height): 一般指mOverscanScreenXxx不包含navigation bar的区域
-   mRestrictedScreenLeft(Top, Width, Height): 当前屏幕的大小, 如果状态栏不能隐藏, 不包含状态栏与导航栏的部分
-   mSystemLeft(Top, Right, Bottom): 在Layout阶段, 系统UI的屏幕边界
-   mStableleft(Top, Right, Bottom): 不包含状态栏， 导航栏的部分. 用于提供给StableContent的区域
-   mStableFullscreenLeft(Top, Right, Bottom): 与mStableXxx类似， 但是包含状态栏， 用于同时满足全屏, Stable属性
-   mForceImmersiveLeft(Top, Right, Bottom): 用于沉浸式
-   mCurLeft(Top, Right, Bottom): 系统装饰(状态栏, 导航栏, 输入法Dock)的边界
-   mContentLeft(Top, Right, Bottom): window展示内容给用户的区域, 一般与mCurXxx相同(除了屏幕装饰有insets时, 此时比mCurXX区域大一点)
-   mDockLeft(Top, Right, Bottom): 输入法Window放置的位置

需要注意的是mContentLeft(xxx)与WindowState中的content不是一回事, PhoneWindowManager中的mContentLeft是WindowState中的visibleFrame对应的大小.

在PhoneWindowManager.java的beginLayoutLw方法中, 在手机中， mOverscanScreenXxx, mUnrestrictedLeft, mSystemXX, mStableLeft一般均是屏幕大小(现代显示屏时没有oversacan这个值的)。 然后layout 导航栏(layoutNavigationVar), 然后layout状态栏(layoutStatusBar)

layout导航栏, 确定导航栏位置(底部, 右边, 左边), 仅分析导航栏位于底部的case: 

-   计算得到:mStableBottom = mStableFullscreenBottom = displayHeight - overscanBottom - navigationBarHeight.
-   若导航栏可见且不是瞬时可见的, 则mContentBottom = mSystemBottom = mDockBottom = 导航栏顶部.

layout状态栏: 

-   状态栏可见且不透明: mContentTop = mDockTop = mUnrestrictedTop(一般为0) + mStatusBarHeight,
-   状态栏可见, 没有动画, 不透明, 不瞬时, 最近没有透明过 mSystemTop = mUnrestrictedTop + mStatusBarHeight


### WindowSurfacePlacer.java

用于放置windows与其surfaces, 整个WindowManagerService只有一个. 
	```java
    final void performSurfacePlacement(boolean force) {
    	if (mDeferDepth > 0 && !force) {
    		return;
    	}
    	int loopCount = 6;
    	do {
    		mTraversalScheduled = false;
    		performSurfacePlacementLoop();
    		mService.mAnimationHandler.removeCallbacks(mPerformSurfacePlacement);
    		loopCount--;
    	} while (mTraversalScheduled && loopCount > 0);
    	mService.mRoot.mWallpaperActionPending = false;
    }
```

其performSurfacePlacement用于触发Window的layout. 

其由:

-   ViewRootImpl的relayoutWindow触发
-   AppWindowToken的setVisibility，可以由AM的ActivityRecord触发
-   AppWindowToken的finishRelaunching
-   AppWindowToken的stopFreezingScreen
-   DisplayContent的layoutAndAssignWindowLayersIfNeeded
-   StackWindowController的resize
-   WindowToke的setExiting


## Surface操控

WindowManagerService在进行窗口布局完成后需要通知SurfaceFlinger窗口位置改变, 那么WM服务如何记录Surface的对应关系, 并且是什么时候通知SurfaceFlinger的呢. 

WindowState对象中有一个WindowStateAnimator属性, WindowStateAnimator的内部属性mSurfaceController作为操控SurfaceController的控制器.
