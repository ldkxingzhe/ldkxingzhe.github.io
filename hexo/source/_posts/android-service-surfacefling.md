---
title: Android Service 之 SurfaceFlinger
date: 2019-12-10 20:15:12
tags: [android, service, surfacefling, BufferQueue]
---
SurfaceFlinger一个native service， 用于合成窗口呈现给用户。 Android通过BufferQueue, 将不同进程的Android组件: WindowManagerService, 应用进程， SurfaceFlinger联系在一起. 这里大致介绍下BufferQueue的实现原理， 另外涉及到SurfaceSession、SurfaceControl, Surface这些基本概念. 

<!-- more  -->
# 基本概念

aosp官网对Graphics的介绍文章<https://source.android.com/devices/graphics>,  首先是Android Graphic系统的关键组件组成:

![img](https://ldk-blog.oss-cn-beijing.aliyuncs.com/blog/ape_fwk_graphics.png)

介绍了整个框架的数据流:

![img](https://ldk-blog.oss-cn-beijing.aliyuncs.com/blog/android_surface_flinger_graphics_pipeline.png)

以及连接各个组件的中间件BufferQueue, 通过BufferQueue这个跨进程方案将Android的图形组件联系在了一起:

![img](https://ldk-blog.oss-cn-beijing.aliyuncs.com/blog/android_surfaceflinger_bufferqueue.png)

本文在此基础上, 研究下各个组件的细节. 


# 中间件BufferQueue

之所以先从BufferQueue这个中间件开始, 跟阅读Framework时先读懂Binder机制的原因相同: 1. 他们都是中间件, 实现上比较独立, 从简单易懂的来. 2. BufferQueue被大量使用, 弄懂其他组件时, 无法绕过BufferQueue. 

首先BufferQueue用于一个Buffer池的队列, 通过Android Binder在进程间传递Buffer, 我们都知道Binder机制由1M的带宽限制, 不适合传输大信息, BufferQueue的Producer与Consumer接口是通过Binder机制调用的, Buffer传输是通过匿名共享内存实现的. 

frameworks/native/include/gui/BufferQueueCore.h文件中描述了BufferQueue的核心结构:
	```cpp
    // 当然还有其他如listener， mIsAbandoned, mConsumerControlledByApp这些属性记录BufferQueue的状态
    // mSlots is an array of buffer slots that must be mirrored on the producer
    // side. This allows buffer ownership to be transferred between the producer
    // and consumer without sending a GraphicBuffer over Binder. The entire
    // array is initialized to NULL at construction time, and buffers are
    // allocated for a slot when requestBuffer is called with that slot's index.
    BufferQueueDefs::SlotsType mSlots;
	```

其中mSlots是一个BufferSlot数组(frameworks/native/libs/gui/include/gui/BufferSlot.h):
	
	```cpp
    // mGraphicBuffer points to the buffer allocated for this slot or is NULL
    // if no buffer has been allocated.
    sp<GraphicBuffer> mGraphicBuffer;
    
    // mBufferState is the current state of this buffer slot.
    BufferState mBufferState;
    
    // mFence is a fence which will signal when work initiated by the
    // previous owner of the buffer is finished. When the buffer is FREE,
    // the fence indicates when the consumer has finished reading
    // from the buffer, or when the producer has finished writing if it
    // called cancelBuffer after queueing some writes. When the buffer is
    // QUEUED, it indicates when the producer has finished filling the
    // buffer. When the buffer is DEQUEUED or ACQUIRED, the fence has been
    // passed to the consumer or producer along with ownership of the
    // buffer, and mFence is set to NO_FENCE.
    sp<Fence> mFence;	
	```

其中GraphicBuffer(frameworks/native/libs/gui/include/ui/GraphicBuffer.h)中记录着Buffer的内存信息(GraphicBufferMapper.h). 其中mBufferState记录的是当前这个Buffer的状态:

-   FREE: 表示这块Buffer可以被Producer dequeued, 此时Buffer的拥有者是BufferQueue, call dequeueBuffer &#x2014;> DEQUEUED
-   DEQUEUED: 表示Buffer已经被Producer占用, 此时procuderr只要收到fence通知，就可以修改缓存内容, 此时Buffer的所有者是producer, call queueBuffer or attachBufferr &#x2013;> QUEUED, call cancelBuffer or detachBuffer &#x2014;> FREE
-   QUEUED: 表示Buffer已经被Producer提交, 一定时间内，Buffer依然可以被Producer修改. call acquireBuffer -> ACQUIRED, or &#x2013;> FREE
-   ACQUIRED: 表示Buffer已经被Consumer获取, 直到对应的fence被通知consumer才可以消费 call releaseBufferr detachBuffer &#x2013;> FREE
-   SHARED: 表示Bufferr在共享模式下

由BufferQueue::createBufferQueue方法可知， BufferQueue producer的服务端实现为BufferQueueProducer, consumer的服务端实现为BufferQueueConsumer


## 生产者视角: IGraphicBufferProducer

由于是一个跨进程通信, 要说IGraphicBufferrProducer在服务端与客户端相关实现, 在Client侧典型实现为Surface, 在Server侧实现是BufferQueueProducer. 
	
	```cpp
    // Client侧:
    class Surface /*:精简掉父类*/ {
      struct BufferSlot {
    	sp<GraphicBuffer> buffer;
    	Region dirtyRegion;
      }
      sp<IGraphicBufferProducer> mGraphicBufferProducer;
      BufferSlot mSlots[NUM_BUFFER_SLOTS];
    }
    
    // Server侧
    class BufferQueueProducer
    {
    	// This references mCore->mSlots. Lock mCore->mMutex while accessing.
    	BufferQueueDefs::SlotsType& mSlots;
    }
	```

在Serverr端与Client端的mSlots是一个镜像关系, 我们的目的就是希望两者状态一致, 所以就有一个主从关系, Server端为主, Client端为从。 更改流程: 

-   dequeueBuffer(告诉Server端, 我需要一个Buffer, 请给我分配一个坑位吧),
-   requestBuffer(我已经占了一个坑位, 现在请将坑位的内存信息发给我吧),
-   attachBuffer: 我已经快画完了，将这块内存提交给BufferQueue通知consumer消费吧
-   queueBuffer: 我画完了, 将这块内存提交给BufferQueue通知consumer消费, 这个是由Java层unLockAndPost调用的

dequeuedBuffer Server端实现简述: 

-   1. 通过waitForFreeSlotThenRelock, 获取一个合适的空槽.
-   2. 校验是否是sharemodel的reallocation.
-   3. 若需要重新分配, 重新构造一个GraphicBuffer并initCheck
-   4. 调用Consumer的addAndGetFrameTimestamps
-   将几号坑位等信息返回给客户端
	```cpp
    status_t BufferQueueProducer::requestBuffer(int slot, sp<GraphicBuffer>* buf) {
    	Mutex::Autolock lock(mCore->mMutex);
    	if (mCore->mIsAbandoned) {
    		BQ_LOGE("requestBuffer: BufferQueue has been abandoned");
    		return NO_INIT;
    	}
    	if (mCore->mConnectedApi == BufferQueueCore::NO_CONNECTED_API) {
    		BQ_LOGE("requestBuffer: BufferQueue has no connected producer");
    		return NO_INIT;
    	}
    	if (slot < 0 || slot >= BufferQueueDefs::NUM_BUFFER_SLOTS) {
    		BQ_LOGE("requestBuffer: slot index %d out of range [0, %d)",
    				slot, BufferQueueDefs::NUM_BUFFER_SLOTS);
    		return BAD_VALUE;
    	} else if (!mSlots[slot].mBufferState.isDequeued()) {
    		BQ_LOGE("requestBuffer: slot %d is not owned by the producer "
    				"(state = %s)", slot, mSlots[slot].mBufferState.string());
    		return BAD_VALUE;
    	}
    
    	mSlots[slot].mRequestBufferCalled = true;
    	*buf = mSlots[slot].mGraphicBuffer;   // 直接将对应卡槽的GraphicBuffer对象进行了回传
    	return NO_ERROR;
    }
	```

回传的Buffer内容见frameworks/native/libs/nativebase/include/nativebase/nativebase.h


## 消费者视角: IGraphicBufferConsumer

略


# SurfaceSession:

Session是一个会话的意思， 在CS架构中比较常见, 用于双方记录一些会话信息. SurfaceSession用来代表一个与surfaceflinger的连接，通过他可以用来创建一个或多个Surrface实例. 

构造位置:

-   由WindowManagerService的构造函数构造, mFxSession = new SurfaceSession()
-   由com.android.server.wm.Session.windowAddedLocked中创建 mSurfaceSession = new SurfaceSession()
-   由SurfaceView.updateSurface中按需构造一个 mSurfaceSession = new SurfaceSession(viewRoot.mSurface);
-   有TaskSnapshotSurface的drawSizeMismatchSnapShot中构造一个

WindowManagerService的mFxSession, 用于水印，进度条之类的系统层UI, 拖拽动画的绘制也是使用这个SurfaceSession的. 

com.android.server.wm.Session对象运行在WindowManagerService所在进程, 构造由openSession方法触发(由WindowManagerGlobal getWindowSession触发). 而Session的windowAddedLocked方法由ViewRootImpl的setView调用Session的addToDisplyXXX触发. 

SurfaceView就是在View preDraw前与scroll后判断下是否需要创建SurfaceSession.

SurfaceSession提供的能力: 

-   SurfaceSession构造函数需要: SurfaceSession的构造函数调用了nativeCreate方法, 创建了一个SurfaceComposerClient对象, SurfaceControl的构造函数的nativeCreate 调用这个SurfaceComposerClient的createSurface创建一个Surface对象.

其中SurfaceComposerClient可以看成ISurfaceComposerClient的Bp端, 


# SurfaceControl:

控制器, 可以对Surface进行一系列的操作, 
java层的构造位置: 

-   WindowSurfacePlacer.java的createThumbnailAppAnimator中构造
-   由SurfaceControlWithBackground的构造函数调用, SurfaceView中
-   由SurfaceControlWithBackground构造, 在WindowSurfaceController中构造.
-   由WindowManagerService.prepareDragSurface创建

native层的构造位置: 

-   SurfaceComposerClient.cpp的createSurface中创建, SurfaceComposerClient由SurfaceSession的jni(nativeCreate)调用创建

SurfaceComposerClient在onFirstRef中通过Binder的surfaceflinger service的 createConnection()构造一个新的连接. 

**Surface:**
Surface是用来操控一块原始buffer数据, Surface通过Binder的IPC机制将Bufferr传递给BufferrQueue(通过producer接口). 


# ISurfaceComposerClient

提供一下方法:
	```cpp
    virtual status_t createSurface(const String8& name, uint32_t w, uint32_t h, PixelFormat format,
    							   uint32_t flags, const sp<IBinder>& parent, uint32_t windowType,
    							   uint32_t ownerUid, sp<IBinder>* handle,
    							   sp<IGraphicBufferProducer>* gbp) = 0;
    
    virtual status_t destroySurface(const sp<IBinder>& handle) = 0;
    virtual status_t clearLayerFrameStats(const sp<IBinder>& handle) const = 0;
    virtual status_t getLayerFrameStats(const sp<IBinder>& handle, FrameStats* outStats) const = 0;
	```

createSurface中调用服务端的createSurface方法, 根据返回值构造了一个SurfaceControl对象:, createSurface其调用位置:

-   android\_view\_SurfaceControl.cpp的nativeCreate(由java层的SurfaceControl构造函数触发)

其服务端实现为frameworks/native/services/surfaceflinger/Client.h
	```cpp
    class Client : public BnSurfaceComposerClient
    {
    public:
    	explicit Client(const sp<SurfaceFlinger>& flinger);
    	Client(const sp<SurfaceFlinger>& flinger, const sp<Layer>& parentLayer);
    	~Client();
    
    	status_t initCheck() const;
    
    	// protected by SurfaceFlinger::mStateLock
    	void attachLayer(const sp<IBinder>& handle, const sp<Layer>& layer);
    
    	void detachLayer(const Layer* layer);
    
    	sp<Layer> getLayerUser(const sp<IBinder>& handle) const;
    
    	void setParentLayer(const sp<Layer>& parentLayer);
    
    private:
    	// ISurfaceComposerClient interface
    	virtual status_t createSurface(
    			const String8& name,
    			uint32_t w, uint32_t h,PixelFormat format, uint32_t flags,
    			const sp<IBinder>& parent, uint32_t windowType, uint32_t ownerUid,
    			sp<IBinder>* handle,
    			sp<IGraphicBufferProducer>* gbp);
    
    	virtual status_t destroySurface(const sp<IBinder>& handle);
    
    	virtual status_t clearLayerFrameStats(const sp<IBinder>& handle) const;
    
    	virtual status_t getLayerFrameStats(const sp<IBinder>& handle, FrameStats* outStats) const;
    
    	virtual status_t onTransact(
    		uint32_t code, const Parcel& data, Parcel* reply, uint32_t flags);
    
    	sp<Layer> getParentLayer(bool* outParentDied = nullptr) const;
    
    	// constant
    	sp<SurfaceFlinger> mFlinger;
    
    	// protected by mLock
    	DefaultKeyedVector< wp<IBinder>, wp<Layer> > mLayers;
    	wp<Layer> mParentLayer;
    
    	// thread-safe
    	mutable Mutex mLock;
    };
	```

在Client中， Surface的概念被偷梁换柱成了Layer. 调用SurfaceFlinger::createLayer方法, 在构造Layer结束后, SurfaceFlinger::createLayer调用了addClientLayer将Layer放置进入LayerStack中. 
	```cpp
    status_t SurfaceFlinger::addClientLayer(const sp<Client>& client,
    		const sp<IBinder>& handle,
    		const sp<IGraphicBufferProducer>& gbc,
    		const sp<Layer>& lbc,
    		const sp<Layer>& parent)
    {
    	// add this layer to the current state list
    	{
    		Mutex::Autolock _l(mStateLock);
    		if (mNumLayers >= MAX_LAYERS) {
    			ALOGE("AddClientLayer failed, mNumLayers (%zu) >= MAX_LAYERS (%zu)", mNumLayers,
    				  MAX_LAYERS);
    			return NO_MEMORY;
    		}
    		if (parent == nullptr) {
    			mCurrentState.layersSortedByZ.add(lbc);
    		} else {
    			if (mCurrentState.layersSortedByZ.indexOf(parent) < 0) {
    				ALOGE("addClientLayer called with a removed parent");
    				return NAME_NOT_FOUND;
    			}
    			parent->addChild(lbc);
    		}
    
    		mGraphicBufferProducerList.add(IInterface::asBinder(gbc));
    		mLayersAdded = true;
    		mNumLayers++;
    	}
    
    	// attach this layer to the client
    	client->attachLayer(handle, lbc);
    
    	return NO_ERROR;
    }
	```

# Layer

Layer是图层合成中最重要的单元, Layer是一个Surface与SurfaceControl的合成体. 每一个Layer有一系列的属性用来定义它如何跟其他层进行交互. 

-   位置信息: 定义当前图层在显示屏上的位置， 包括四点位置, 以及对应的Z-order
-   内容信息: 定义如何裁剪内容
-   合成信息: 定义如何跟其他图层合成, 比如说blending模式， alpha值等

在Layer对象第一次被引用时(onFirstRef), 一个新的BufferQueue与SurfaceFlingerConsumer被构造. 
	```cpp
    void Layer::onFirstRef() {
    	// Creates a custom BufferQueue for SurfaceFlingerConsumer to use
    	sp<IGraphicBufferProducer> producer;
    	sp<IGraphicBufferConsumer> consumer;
    	BufferQueue::createBufferQueue(&producer, &consumer, true);
    	mProducer = new MonitoredProducer(producer, mFlinger, this);
    	mSurfaceFlingerConsumer = new SurfaceFlingerConsumer(consumer, mTextureName, this);
    	mSurfaceFlingerConsumer->setConsumerUsageBits(getEffectiveUsage(0));
    	mSurfaceFlingerConsumer->setContentsChangedListener(this);
    	mSurfaceFlingerConsumer->setName(mName);
    
    	if (mFlinger->isLayerTripleBufferingDisabled()) {
    		mProducer->setMaxDequeuedBufferCount(2);
    	}
    
    	const sp<const DisplayDevice> hw(mFlinger->getDefaultDisplayDevice());
    	updateTransformHint(hw);
    }
	```

Layer对象的内部属性: 

-   regions信息: visibleRegion, converedRegion, visibleNonTransparentRegion, surfaceDamageRegion;
-   sequence: Layer序号, 用于解决多个Layer拥有多个相同的Z-order信息时确定上下级关系
-   State信息(mCurrentState, mDrawingState): 
    -   一个active几何位置信息;
    -   一个requested几何位置信息;
    -   z;
    -   layerStack 所属LayerStack;
    -   alpha;
    -   其他
-   mSurfaceFlingerConsumer, mProducer


# SurfaceFlinger中的LayerStacks概念

我们知道Surface的概念，在SurfaceFlinger中的对应概念为Layer:
	```cpp
    void SurfaceFlinger::rebuildLayerStacks() {
    	ATRACE_CALL();
    	ALOGV("rebuildLayerStacks");
    
    	// rebuild the visible layer list per screen
    	if (CC_UNLIKELY(mVisibleRegionsDirty)) {
    		ATRACE_CALL();
    		mVisibleRegionsDirty = false;
    		invalidateHwcGeometry();
    
    		for (size_t dpy=0 ; dpy<mDisplays.size() ; dpy++) {
    			Region opaqueRegion;
    			Region dirtyRegion;
    			Vector<sp<Layer>> layersSortedByZ;
    			const sp<DisplayDevice>& displayDevice(mDisplays[dpy]);
    			const Transform& tr(displayDevice->getTransform());
    			const Rect bounds(displayDevice->getBounds());
    			if (displayDevice->isDisplayOn()) {
    				// 显示设备亮着情况下, 计算有效的显示区域
    				computeVisibleRegions(displayDevice, dirtyRegion, opaqueRegion);
    
    				// 根据ZOrder遍历所有Layer
    				mDrawingState.traverseInZOrder([&](Layer* layer) {
    					if (layer->belongsToDisplay(displayDevice->getLayerStack(),
    								displayDevice->isPrimary())) {
    						Region drawRegion(tr.transform(
    								layer->visibleNonTransparentRegion));
    						drawRegion.andSelf(bounds);
    						if (!drawRegion.isEmpty()) {
    							layersSortedByZ.add(layer);
    						} else {
    							// Clear out the HWC layer if this layer was
    							// previously visible, but no longer is
    							layer->destroyHwcLayer(
    									displayDevice->getHwcDisplayId());
    						}
    					} else {
    						// WM changes displayDevice->layerStack upon sleep/awake.
    						// Here we make sure we delete the HWC layers even if
    						// WM changed their layer stack.
    						layer->destroyHwcLayer(displayDevice->getHwcDisplayId());
    					}
    				});
    			}
    			displayDevice->setVisibleLayersSortedByZ(layersSortedByZ);
    			displayDevice->undefinedRegion.set(bounds);
    			displayDevice->undefinedRegion.subtractSelf(
    					tr.transform(opaqueRegion));
    			displayDevice->dirtyRegion.orSelf(dirtyRegion);
    		}
    	}
    }
	```
mDrawingState是SurfaceFlinger内部定义的一个类, 结构如下:
	```cpp
    class State{
    		LayerVector layersSortedByZ;
    		DefaultKeyedVector< wp<IBinder>, DisplayDeviceState> displays;
    }
	```

