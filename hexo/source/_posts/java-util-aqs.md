---
title: java.util.concurrent下的同步器
date: 2019-10-15 23:50:07
tags: [jvm, concurrent, lock]
---
![img](https://ldk-blog.oss-cn-beijing.aliyuncs.com/blog/concurrent.jpeg)
java.util.concurrent中包含了大量的多线程相关的工具与集合类, 这里介绍下AbstractQueuedSynchronizer基类及其经典实现(各种同步器)
<!-- more -->

同步器提供了高级别的同步API, 有五种: Semaphore, CountDownLatch, CyclicBarrier, Phaser, Exchanger. 分析各自源码前先看下AQS(AbstractQueuedSynchronizer), 这个基类在大部分同步器的实现中被用到。

# AbstractQueuedSynchronizer

AQS提供了共享锁(SHARE)与排他锁(EXCLUSIVE)两种锁模式, 

其核心是一个FIFO的队列, 并且结合使用了JVM内部的API(CAS 一些列的compareAndSet方法)。 其还维护了一个Int型的State(volatile)

内部由一个FIFO的队列, 其中节点Node结构如下:
	```java
	static final class Node {
    	volatile int waitStatus;     // 当前节点的状态, >0 表示取消
    	volatile Node prev;          
    	volatile Node next;
    	volatile Thread thread;
    	Node nextWaiter;             // 被Condition锁着， 不需要加锁, 一般是SHARED, 或者是EXCLUSIVE对象
	}
	private volatile int state;      // 通过compareAndSet内部方法保证
	```
AQS中的线程挂起与唤醒同样使用JVM内部API, 由LockSupport封装进行park与unpark. 用于避免Thread本身函数出现的问题, 实例见unparkSuccessor(Node node), 指定挂起时间之类的也是由LockSupport实现的. 

好奇心害死猫， 来看下LockSupport中park与compareAndSet的方法内部实现。 park的实现只看posix版本的, 是pthread的封装
	```java
    // void Parker::park(bool isAbsolute, jlong time)
      if (time == 0) {
    	status = pthread_cond_wait(&_cond[_cur_index], _mutex);
    	assert_status(status == 0, status, "cond_timedwait");
      }
      else {
    	_cur_index = isAbsolute ? ABS_INDEX : REL_INDEX;
    	status = pthread_cond_timedwait(&_cond[_cur_index], _mutex, &absTime);
    	assert_status(status == 0 || status == ETIMEDOUT,
    				  status, "cond_timedwait");
      }
	```

compareAndSetInt的实现位于unsafe.cpp的Unsafe\_CompareAndSetInt中, 跳转的核心实现是进入了汇编代码, 具体内容跟CPU有关
	```java
    // Define the class before including platform file, which may specialize
    // the operator definition.  No generic definition of specializations
    // of the operator template are provided, nor are there any generic
    // specializations of the class.  The platform file is responsible for
    // providing those.
    template<size_t byte_size>
    struct Atomic::PlatformCmpxchg {
      template<typename T>
      T operator()(T exchange_value,
    			   T volatile* dest,
    			   T compare_value,
    			   atomic_memory_order order) const;
    };
	```

# Semaphore(旗语)

一个计数旗语, 理论上包含一系列通行证, 每个acquire方法将阻塞到一个通行证可行, 每个release将释放一个通行证. 实际上Semaphore内部并没有这些通行证对象, Semaphore仅仅保存可用数量而已. 

Semaphore常用于限制可访问的资源数量, 根据其目的， 应该使用共享锁模式, 又分为公平同步器与非公平同步器. 
	```java
    package ldk.learning.concurrency;
    
    import java.util.concurrent.*;
    
    public class SemaphoreDemo {
    
    	private Semaphore semaphore = new Semaphore(2);
    	private StringBuilder[] stringBuilders = new StringBuilder[]{
    			new StringBuilder(),
    			new StringBuilder()
    	};
    	private boolean[] used = new boolean[2];
    
    	public StringBuilder chooseStringBuilder(){
    		semaphore.acquireUninterruptibly();
    		for (int i = 0; i < used.length; i++) {
    			if (!used[i]){
    				synchronized (this){
    					if (!used[i]){
    						used[i] = true;
    						return stringBuilders[i];
    					}
    				}
    			}
    		}
    		throw new IllegalStateException("Can't be Here");
    	}
    
    	public void releaseStringBuilder(StringBuilder stringBuilder){
    		for (int i = 0; i < stringBuilders.length; i++) {
    			if (stringBuilders[i] == stringBuilder){
    				used[i] = false;
    				semaphore.release();
    				break;
    			}
    		}
    	}
    
    	public void work(StringBuilder stringBuilder) throws InterruptedException {
    		stringBuilder.append("thread=").append(Thread.currentThread()).append('\n');
    		Thread.sleep(300);
    	}
    
    	@Override
    	public String toString() {
    		return "(1 =\n " + stringBuilders[0] + "\n\n\n\n 2=\n " + stringBuilders[1];
    	}
    
    
    	public static void main(String[] args) throws InterruptedException {
    		SemaphoreDemo demo = new SemaphoreDemo();
    		ExecutorService threadPool = Executors.newCachedThreadPool();
    		for (int i = 0; i < 100; i++) {
    			threadPool.execute(() -> {
    				StringBuilder stringBuilder = demo.chooseStringBuilder();
    				try {
    					demo.work(stringBuilder);
    				} catch (InterruptedException e) {
    					e.printStackTrace();
    				}finally {
    					demo.releaseStringBuilder(stringBuilder);
    				}
    			});
    		}
    		threadPool.shutdown();
    		threadPool.awaitTermination(10, TimeUnit.MINUTES);
    		System.out.println(demo.toString());
    	}
    }
	```

# CountDownLatch计数器

实际上就是讲state即为当前剩余的数字， 主线程一直尝试获取共享锁， 每次释放一个数字时唤醒主线程判断下, 直到state值为0时获取共享锁. 核心相关代码应该是AQS的doAcquireSharedInterruptibly
	```java
    /**
     * Acquires in shared interruptible mode.
     * @param arg the acquire argument
     */
    private void doAcquireSharedInterruptibly(int arg)
    	throws InterruptedException {
    	final Node node = addWaiter(Node.SHARED);
    	boolean failed = true;
    	try {
    		for (;;) {
    			final Node p = node.predecessor();
    			if (p == head) {
    				int r = tryAcquireShared(arg);
    				if (r >= 0) {
    					setHeadAndPropagate(node, r);
    					p.next = null; // help GC
    					failed = false;
    					return;
    				}
    			}
    			if (shouldParkAfterFailedAcquire(p, node) &&
    				parkAndCheckInterrupt())
    				throw new InterruptedException();
    		}
    	} finally {
    		if (failed)
    			cancelAcquire(node);
    	}
    }
	```

# CyclicBarrier(同步屏障)

同步屏障是让所有线程等待， 直至某个条件完成.  内部由count进行计数. 利用了ReentrantLock这个锁。


# ReentrantLock可重入锁

ReentrantLock是排他式的可重入锁, 其机制类似于synchronized方式. 由于是排他模式的锁, 可通过getExclusiveOwnerThread获取当前锁持有者的线程对象. 

它同样利用了AQS这个基类.  state值有两个值1, 0. 分别代表持有与否. 通过记录thread记录当前锁的持有者. 


# ReentrantReadWriteLock可重入的读写分离锁

读写分离锁同时使用了AQS的共享与排他模式, 应该是这些同步器中实现最复杂的一个了.  read锁与write锁的获取方式大致相同


## 获取read锁

看获取读锁的还是比较简单明了的， 有排他锁且排他锁不是自身时， 不允许获取read锁. 否则获取并将相应的引用计数+1, 一个大Spin. 无限循环直至OK
	```java
    // 尝试获取read锁
    final boolean tryReadLock() {
    	Thread current = Thread.currentThread();
    	for (;;) {
    		int c = getState();
    		if (exclusiveCount(c) != 0 &&
    			getExclusiveOwnerThread() != current)
    			return false;
    		int r = sharedCount(c);
    		if (r == MAX_COUNT)
    			throw new Error("Maximum lock count exceeded");
    		if (compareAndSetState(c, c + SHARED_UNIT)) {
    			if (r == 0) {
    				firstReader = current;
    				firstReaderHoldCount = 1;
    			} else if (firstReader == current) {
    				firstReaderHoldCount++;
    			} else {
    				HoldCounter rh = cachedHoldCounter;
    				if (rh == null || rh.tid != getThreadId(current))
    					cachedHoldCounter = rh = readHolds.get();
    				else if (rh.count == 0)
    					readHolds.set(rh);
    				rh.count++;
    			}
    			return true;
    		}
    	}
    }
	```
直接调用read锁的lock方法时， 调用了AQS的tryAcquireShared(int unused)方法
	```java
    protected final int tryAcquireShared(int unused) {
    	Thread current = Thread.currentThread();
    	int c = getState();
    	if (exclusiveCount(c) != 0 &&
    		getExclusiveOwnerThread() != current)
    		return -1;
    	int r = sharedCount(c);
    	if (!readerShouldBlock() &&
    		r < MAX_COUNT &&
    		compareAndSetState(c, c + SHARED_UNIT)) {
    		if (r == 0) {
    			firstReader = current;
    			firstReaderHoldCount = 1;
    		} else if (firstReader == current) {
    			firstReaderHoldCount++;
    		} else {
    			HoldCounter rh = cachedHoldCounter;
    			if (rh == null || rh.tid != getThreadId(current))
    				cachedHoldCounter = rh = readHolds.get();
    			else if (rh.count == 0)
    				readHolds.set(rh);
    			rh.count++;
    		}
    		return 1;
    	}
    	return fullTryAcquireShared(current);
    }
	```
可以看出大部分地方与上边的tryLock一直, 等待代码在fullTryAcquireShared的方法中. 
	```java
    final int fullTryAcquireShared(Thread current) {
    	 HoldCounter rh = null;
    	 for (;;) {
    		 int c = getState();
    		 if (exclusiveCount(c) != 0) {
    			 if (getExclusiveOwnerThread() != current)
    				 return -1;
    			 // else we hold the exclusive lock; blocking here
    			 // would cause deadlock.
    		 } else if (readerShouldBlock()) {
    			 // Make sure we're not acquiring read lock reentrantly
    			 if (firstReader == current) {
    				 // assert firstReaderHoldCount > 0;
    			 } else {
    				 if (rh == null) {
    					 rh = cachedHoldCounter;
    					 if (rh == null || rh.tid != getThreadId(current)) {
    						 rh = readHolds.get();
    						 if (rh.count == 0)
    							 readHolds.remove();
    					 }
    				 }
    				 if (rh.count == 0)
    					 return -1;
    			 }
    		 }
    		 if (sharedCount(c) == MAX_COUNT)
    			 throw new Error("Maximum lock count exceeded");
    		 if (compareAndSetState(c, c + SHARED_UNIT)) {
    			 if (sharedCount(c) == 0) {
    				 firstReader = current;
    				 firstReaderHoldCount = 1;
    			 } else if (firstReader == current) {
    				 firstReaderHoldCount++;
    			 } else {
    				 if (rh == null)
    					 rh = cachedHoldCounter;
    				 if (rh == null || rh.tid != getThreadId(current))
    					 rh = readHolds.get();
    				 else if (rh.count == 0)
    					 readHolds.set(rh);
    				 rh.count++;
    				 cachedHoldCounter = rh; // cache for release
    			 }
    			 return 1;
    		 }
    	 }
     }
	```
