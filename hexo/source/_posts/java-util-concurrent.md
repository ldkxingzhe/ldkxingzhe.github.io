---
title: java.util.concurrent包及其源码
date: 2019-10-15 15:37:38
tags: [java, concurrent]
---

![img](https://ldk-blog.oss-cn-beijing.aliyuncs.com/blog/concurrent.jpeg)
java.util.current中包含了大量的多线程相关的工具与集合类， 主要包括同步器, 线程池, 并发容器. 
博客的标题是从旧标题中延续过来的, 短短的一篇博客， 不可能能够详细的描述整个current, 我将尽可能的完善. 

<!-- more  -->
# Synchronizers(同步器)

提供了一下五中同步器: Semaphore, CountDownLatch, CyclicBarrier, Phaser, Exchanger. 


## AbstractQueuedSynchronizer

在讲java.util.concurrent包下的各种同步器与锁前, 需要了解一下AbstractQueuedSynchronizer(AQS)这个基类. AQS提供了共享锁(SHARE)与排他锁(EXCLUSIVE)两种锁模式, 需要我们在实现同步器子类时选择一种模式(only one). 其核心是一个FIFO的队列, 并且结合使用了JVM内部的API(CAS 一些列的compareAndSet方法)。 其还维护了一个Int型的State(volatile)

内部由一个FIFO的队列, 其中节点Node结构如下:

    	static final class Node {
    	static final Node SHARED = new Node();
    	static final Node EXCLUSIVE = null;
    
    	static final int CANCELLED =  1;
    	static final int SIGNAL    = -1;
    	static final int CONDITION = -2;
    	static final int PROPAGATE = -3;
    
    	/**
    	 * Status field, taking on only the values:
    	 *   SIGNAL:     The successor of this node is (or will soon be)
    	 *               blocked (via park), so the current node must
    	 *               unpark its successor when it releases or
    	 *               cancels. To avoid races, acquire methods must
    	 *               first indicate they need a signal,
    	 *               then retry the atomic acquire, and then,
    	 *               on failure, block.
    	 *   CANCELLED:  This node is cancelled due to timeout or interrupt.
    	 *               Nodes never leave this state. In particular,
    	 *               a thread with cancelled node never again blocks.
    	 *   CONDITION:  This node is currently on a condition queue.
    	 *               It will not be used as a sync queue node
    	 *               until transferred, at which time the status
    	 *               will be set to 0. (Use of this value here has
    	 *               nothing to do with the other uses of the
    	 *               field, but simplifies mechanics.)
    	 *   PROPAGATE:  A releaseShared should be propagated to other
    	 *               nodes. This is set (for head node only) in
    	 *               doReleaseShared to ensure propagation
    	 *               continues, even if other operations have
    	 *               since intervened.
    	 *   0:          None of the above
    	 *
    	 * The values are arranged numerically to simplify use.
    	 * Non-negative values mean that a node doesn't need to
    	 * signal. So, most code doesn't need to check for particular
    	 * values, just for sign.
    	 *
    	 * The field is initialized to 0 for normal sync nodes, and
    	 * CONDITION for condition nodes.  It is modified using CAS
    	 * (or when possible, unconditional volatile writes).
    	 */
    	volatile int waitStatus;
    
    	volatile Node prev;
    
    	volatile Node next;
    
    	volatile Thread thread;
    
    	/**
    	 * Link to next node waiting on condition, or the special
    	 * value SHARED.  Because condition queues are accessed only
    	 * when holding in exclusive mode, we just need a simple
    	 * linked queue to hold nodes while they are waiting on
    	 * conditions. They are then transferred to the queue to
    	 * re-acquire. And because conditions can only be exclusive,
    	 * we save a field by using special value to indicate shared
    	 * mode.
    	 */
    	Node nextWaiter;
    
    	final boolean isShared() {
    		return nextWaiter == SHARED;
    	}
    
    	final Node predecessor() throws NullPointerException {
    		Node p = prev;
    		if (p == null)
    			throw new NullPointerException();
    		else
    			return p;
    	}
    
    	Node() {    // Used to establish initial head or SHARED marker
    	}
    
    	Node(Thread thread, Node mode) {     // Used by addWaiter
    		this.nextWaiter = mode;
    		this.thread = thread;
    	}
    
    	Node(Thread thread, int waitStatus) { // Used by Condition
    		this.waitStatus = waitStatus;
    		this.thread = thread;
    	}
    }

**共享锁模式:** 此模式的经典实现包括了Semaphore, CountDownLatch等计数式的同步器。 tryAcquireShared返回一个数值， 暗示当前可用的共享数量, 这样可以将锁向后传递

**排他锁模式:** 此锁的经典实现包括了ReentrantLock, 一般结合AQS的ConditionObject使用. 而且AQS的父类AbstractOwnableSynchronizer就是一个典型的排他式

AQS的锁抢占模式有公平锁与非公平锁两种, 公平锁时使用hasQueuedPredecessors这类方法判断是否合适抢占, 否则放弃

AQS中的线程挂起与唤醒同样使用JVM内部API, 由LockSupport封装进行park与unpark. 用于避免Thread本身函数出现的问题. 


## Semaphore(旗语)

一个计数旗语, 理论上包含一系列通行证, 每个acquire方法将阻塞到一个通行证可行, 每个release将释放一个通行证. 实际上Semaphore内部并没有这些通行证对象, Semaphore仅仅保存可用数量而已. 

Semaphore常用语限制可访问的资源数量

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


## CountDownLatch计数器

这个使用就比较简单了, 原理上就是在tryAcquireShared中判断当前状态. 如果当前状态为0则Ok

    CountDownLatch latch = new CountDownLatch(100);
    ExecutorService threadPool = Executors.newFixedThreadPool(20);
    for (int i = 0; i < 100; i++) {
    	threadPool.execute(() -> {
    		try {
    			Thread.sleep(300);
    		} catch (InterruptedException e) {
    			e.printStackTrace();
    		}finally {
    			latch.countDown();
    		}
    	});
    }
    threadPool.shutdown();
    latch.await();
    System.out.println("100个计数已经完成");


## CyclicBarrier(同步屏障)

类似CountDownLatch, 不过是await多, 使用了ReentrantLock


## ReentrantLock可重入锁

ReentrantLock是排他式的可重入锁, 其机制类似于synchronized方式. 由于是排他模式的锁, 可通过getExclusiveOwnerThread获取当前锁持有者的线程对象. 


# ThreadPoolExecutor

Java的线程池, 最常用的一个, 可以完整的展现java线程池是如何重用Thread, 如何进行异常处理的. 

包含的特殊属性: 

    // 用于表示这个线程池的状态
    private final AtomicInteger ctl = new AtomicInteger(ctlOf(RUNNING, 0));
    
    // 用户缓存Tasks, 会阻塞的
    private final BlockingQueue<Runnable> workQueue;
    
    // 用于表示用于工作的线程workers
    private final HashSet<Worker> workers = new HashSet<Worker>();

真正处理Task的方法是runWorker, 通过循环遍历获取workQueue中的Task， 并且处理它. 


# ThreadLocal

ThreadLocal并不是java.util.concurrent下的包, 不过在多线程并发中经常用到， 也在这里说明一下. 在每个Thread对象中有一个threadLocals的Map属性， 这些线程独有的属性都来自于这个Map。 很巧妙的设计. 

