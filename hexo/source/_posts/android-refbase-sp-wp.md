---
title: Android RefBase类与强弱引用sp,wp
date: 2019-10-26 18:02:53
tags: [android, refbase]
---
为了能够自动回收C++的对象， google使用sp与wp两个模板类使用引用计数的方式自动对C++对象进行回收, 作为阅读Android C/C++源码必要的基础, 从源码角度剖析下实现原理
<!-- more  -->

# 数据结构

RefBase是所有引用计数gc对象的基类, 引入了一个内部属mRefs进行状态维护。 其内部属属性为:

    std::atomic<int32_t>    mStrong;
    std::atomic<int32_t>    mWeak;
    RefBase* const          mBase;     // 指向外部类
    std::atomic<int32_t>    mFlags;

其中mFlags表示为改对象的生命状态: OBJECT\_LIFETIME\_STRONG(0x0000), OBJECT\_LIFETIME\_WEAK(0x0001) 初始值是0， 也即是说整个对象默认是强引用计数. 
mStrong初始值是(1<<28)一个很大的数字, 代表强引用数量.  mWeak初始值为0, 代表弱引用数量. 


# 算法

各属性值的关键节点与描述

<table border="2" cellspacing="0" cellpadding="6" rules="groups" frame="hsides">


<colgroup>
<col  class="org-right" />

<col  class="org-right" />

<col  class="org-right" />

<col  class="org-right" />

<col  class="org-left" />
</colgroup>
<tbody>
<tr>
<td class="org-right">No</td>
<td class="org-right">mStrong</td>
<td class="org-right">mWeak</td>
<td class="org-right">mFlags</td>
<td class="org-left">Description</td>
</tr>


<tr>
<td class="org-right">1</td>
<td class="org-right">0x10000000000000</td>
<td class="org-right">0</td>
<td class="org-right">0</td>
<td class="org-left">初始状态</td>
</tr>


<tr>
<td class="org-right">2</td>
<td class="org-right">1</td>
<td class="org-right">1</td>
<td class="org-right">0</td>
<td class="org-left">调用incStrong</td>
</tr>


<tr>
<td class="org-right">3</td>
<td class="org-right">0</td>
<td class="org-right">1</td>
<td class="org-right">0</td>
<td class="org-left">调用incWeak</td>
</tr>


<tr>
<td class="org-right">4</td>
<td class="org-right">1</td>
<td class="org-right">2</td>
<td class="org-right">0</td>
<td class="org-left">attemptIncStrong</td>
</tr>
</tbody>
</table>

算法在实现过程中, 考虑到了多线程与多CPU架构下对计算指令的影响， 所以使用std::atomic这个原子整数. 算法比较简单: 


### incStrong

强引用计数+1时, 弱引用计数+1

-   调用mRefs.incWeak()
-   mStrong值加1，并获取mStrong的老值, 如果mStrong的老值不是1 << 28则结束
-   将mStrong值置为1， 并调用onFirstRef

从初始状态(No.1) 调用incStrong后变成状态(No.2)


### decStrong

强引用计数-1时, 弱引用计数-1， 弱此时是强引用计数模式, 且强引用计数为0, 回收该对象

-   mStrong值减1， 并获取老值
-   若老值为1, 调用onLastStringRef,  如果flags 包含了OBJECT\_LIFETIME\_STRONG时， delete this.
-   调用mRefs.decWeak()

从状态No.2 &#x2013;> No.1


### attemptIncStrong(weakref\_type)

首先弱引用计数加1, 尝试强引用计数+1， 如果此时是弱引用计数模式, 会调用onIncStrongAttempted来请示是否允许强引用加1

-   调用incWeak
-   获取mStrong值, 如果存在有效mStrong, 加1, 结束
-   如果flags为Strong时， mStrong加1， 如果不是Strong， 则进行尝试自救onIncStrongAttempted

调用此函数之前， case为No.3, 调用之后, case为No.4


### mRefs.incWeak

mWeak值加1， 从原始状态(No.1)调用incWeak后变成状态(No.3)


### mRefs.decWeak

-   mWeak值减1， 如果mWeak不为0则返回
-   如果flags包含OBJECT\_LIFETIME\_STRONG: delete mRefs引用(这里需要结合RefBase的析构函数)
-   如果flags不包含OBJECT\_LIFETIME\_STRONG: 调用onLastWeakRef, delete RefBase


# sp与wp


### 强引用sp

核心属性: m\_ptr: RefBase的对象指针

-   构造时调用RefBase的incStrong
-   析构时调用RefBase的decStrong

于此同理wp实现类似， 均将实现代理给了RefBase中


### 由弱生强 promote():

直接调用m\_refs的attemptIncStrong:


### 生死魔咒 extendsObjectLifetime(int32\_t)

这里进行设置flags属性罢了
