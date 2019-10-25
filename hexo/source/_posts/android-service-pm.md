---
title: android service 之pm
date: 2019-10-25 15:19:19
tags: [android, pm]
---

pm 是Android的包管理器, 对应着包安装， 删除， 信息查看等操作. 其主Service为 PackageManagerService, 对权限的限制部分也在PackageManagerService中。 由于PM服务中有大量的InstantApp的处理代码， 忽略这部分代码. 
<!-- more -->

# 源码粗略

在pm服务中， 有属性mActivities, mReceivers, mServices, mProviders四个IntentResolver， 分别对应Android的四大组件。 在系统启动， 安装， 删除， 移动时这些会进行相应的更新. 而且这些信息是时时刻刻都在内存中的， 可以明确说过多的安装应用， 即使不运行也会拖慢运行速度。 

PackageManagerService类中有很多get方法用于query. 


## mPackages的写入(commitPackageSettings)

mPackages作为一个记录包与对应包信息的Map, 其写入是PM服务的第一步. 其写入位置只有一个即

-   commitPackageSettings(Package pkg, PackageSetting pkgSetting, UserHandle user, int scanFlags, boolean chatty)

其由scanPackageLI调用, 最终的调用来源: 

-   installNewPackageLIF: 安装一个不存在的安装包
-   replaceNonSystemPackageLIF:
-   replaceSystemPackageLIF:
-   scanDirLI:
-   PackageManagerService的构造函数
-   decompressSystemApplications
-   setEnableSetting
-   loadMediaPackages
-   loadPrivatePackagesInner
-   installPackageFromSystemLIF


## PackageHandler

PackageManagerService中有一个消息循环, PackageHandler是其Handler。 这个线程用于bind service， 并与该Service通信. 该Service是"com.android.defcontainer.DefaultContainerService", 使用这个单独Service的目的是为了防止在COPY和检查apk文件时， 对应的文件所在磁盘被移除， 而进程被内核kill的情况, 防止系统进程收到影响. 

-   第一步: 下发INIT\_COPY指令， 用于检测Service绑定状态, 并记录安装信息
-   第二步: Service绑定后, 下发MSC\_BOUND绑定成功消息, 从记录的需要安装的信息中取出第一个开始处理copy
-   第三步: service.getMinimalPackageInfo, 然后校验各种信息
-   第四步: 调用InstallArg.copyApk开始copy(最终调用service.copyPackage这个方法)

其中第三步与第四步之间可能会存在异步的校验， 待校验完成后会通过PackageHandler抛出PACKAGE\_VERIFIED, CHECK\_PENDING\_VERIFICATION这两个消息(各大厂商提示安装包非官方包应该是通过这里做的), 支持复制步骤完成. 

-   第五步: processPendingInstall，
-   第六步: 调用installPackageTracedLI, 这里就与commitPackageSettings连接上了


## Installer与Installd

Installer是一个系统服务, 集成自SystemService, 是一个Java层的包装, 通过Binder与native服务"installd"进行通信服务， 可以理解为Installd的一层壳. 

提供能力如下:
createAppData, migrateAppData, clearAppData, destroyAppData等操作AppData的能力, 获取AppSize, dexopt, 操控profile等能力. 

其真实实现为InstalldNativeService.cpp(framewors/native/cmds/installd/InstalldNativeService.cpp)
