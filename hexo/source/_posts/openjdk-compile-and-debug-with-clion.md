---
title: openjdk12 编译与调试
date: 2019-10-15 11:27:00
tags: [jvm, c]
---

之所以首先从OpenJDK的源码编译与调试开始，是因为后续的博客在重新整理过程中会加上JDK源码相关的代码验证。本文从源码下载，按需编译，导入clion调试， 笔者在MacOS与Linux验证通过.

<!-- more -->
# 源码下载

编译版本为: jdk-12+33, 从openjdk官网下载即可: <http://hg.openjdk.java.net/jdk/jdk/archive/b67884871b5f.tar.bz2>
由于是Http协议下载，注意校验完整性，编译完整后也要test一下。

提供下jdk-12+33这个版本MD5值: f037c5b729bdc4066ada56ae860c0797


# 编译配置

OpenJDK的编译说明在源码的doc/building.md, 仔细阅读下即可.

OpenJDK作为顶级项目，一般在发布版本的源码在各个编译环境下都没有太大问题。笔者这里使用这个版本在MacOS中编译直接通过了，但在ArchLinux中由于gcc版本过高(当前版本: gcc (GCC) 9.2.0), 源码会提示语法错误，根据需要改下，提供下笔者的[diff文件](https://ldk-blog.oss-cn-beijing.aliyuncs.com/blog/openjdk12-33-gcc-9.diff.txt)

编译时可选配置如下: 

-  --with-debug-level=slowdebug 开启debug
-  --with-boot-jdk=<path> jdk11的路径(本人默认环境时JDK8的，所以需要手动配置)

``` shell
bash configurre --with-debug-level=slowdebug --with-boot-jdk=<path>
```

接下来就可以直接make了, 后续改动一般不需要重新configure了
	
	```shell
    cd build    #进入build 目录
    cd macosx-x86_64-server-slowdebug     #这个目录不同平台， 不同配置可能不一样，根据自己的来
    make
    ```

make成功即可，代表OpenJDK编译完成. 如果有错误，看看是不是gcc版本问题，按需更改下语法一般即可. 

	```shell
    $ ./jdk/bin/java --version
    
    openjdk 12-internal 2019-03-19
    OpenJDK Runtime Environment (slowdebug build 12-internal+0-adhoc.xingzhe.jdk12-b67884871b5f)
    OpenJDK 64-Bit Server VM (slowdebug build 12-internal+0-adhoc.xingzhe.jdk12-b67884871b5f, mixed mode)
	```


# 调试


## 命令行调试

两种调试手段, 一种是使用gdb或者lldb直接命令行调试，直接gdb或lldb启动即可. 

	``` shell
	$ cd jdk/bin/
	$ lldb ./java
	(lldb) b 117
	(lldb) r --version
	Process 32591 launched: './java' (x86_64)
	Process 32591 stopped
	* thread #1, queue = 'com.apple.main-thread', stop reason = breakpoint 1.1
		frame #0: 0x0000000100001794 java`main(argc=2, argv=0x00007ffeefbff8d8) at main.c:117
		114 	            ? sizeof(const_extra_jargs) / sizeof(char *)
		115 	            : 0; // ignore the null terminator index
		116 	
	 -> 117 	        if (main_jargc > 0 && extra_jargc > 0) { // combine extra java args
		118 	            jargc = main_jargc + extra_jargc;
		119 	            list = JLI_List_new(jargc + 1);
		120 	
	Target 0: (java) stopped.
	```

各方面都比较简单, 值得注意的是gdb与lldb会捕获SIGBUS, SIGSEGV错误， 这个不影响虚拟机运行的, 可在命令行中忽略捕捉改信号量


## Clion导入调试

命令行调试总归没有图形化界面调试起来方便, 特别是针对想JDK这样比较大点的项目。 由于对Idea比较熟悉, 这里选择的IDE是其变种Clion。 Clion先天支持Cmake， 否则导入源码过于头疼， 

在项目根目录新加CMakeLists.txt：
	``` shell
    cmake_minimum_required(VERSION 3.7)
    project(hotspot)
    
    include_directories(
    		src/hotspot/cpu
    		src/hotspot/os
    		src/hotspot/os_cpu
    		src/hotspot/share
    		src/hotspot/share/precompiled
    		src/hotspot/share/include
    		src/java.base/unix/native/include
    		src/java.base/share/native/include
    		src/java.base/share/native/libjli
    )
    
    file(GLOB_RECURSE SOURCE_FILES "*.cpp" "*.hpp" "*.c" "*.h")
    add_executable(hotspot ${SOURCE_FILES})	
	```

然后根据自动生成配置文件:
	```shell
    mkdir cmake-build-debug
    cd mkdir cmake-build-debug
    cmake ../
	```

用Clion打开cmake-build-debug项目即可, 待索引完成后. 

Edit Configuration添加一个CMakeApplication， 配置如下图: 
![img](https://ldk-blog.oss-cn-beijing.aliyuncs.com/blog/openjdk_build_debug_configuration.png)

-   注意Executable对象为编译产物java(或其他你需要调试的可执行产物), 位于编译目录的jdk/bin/java中
-   Before launch一项中，删除Build，因为我们不使用Cmake进行编译
-   点击运行，如果正常会输出想要的输出
-   在理想位置打断点，点击调试即可

**NOTE: 在Mac环境下, 我使用Clion进行调试时, 由于SIGSEGV错误， clion调用lldb会直接退出调试, 所以需要切换到gdb调试才可以.**

比如调试java &#x2013;version, 短点在 src/java.base/share/native/libjli/java.c: 445 PrintJavaVersion这里, 点击调试: 

首先得到的是一个SIGSEGV错误, 忽略他即可， Resume Programm:

![img](https://ldk-blog.oss-cn-beijing.aliyuncs.com/blog/openjdk_compile_sigsegv.png)

继续几次就能到咱们打断点的位置: 

![img](https://ldk-blog.oss-cn-beijing.aliyuncs.com/blog/openjdk_compile_debug_printversion.png)

至此调试完成， 虽然使用IDE进行调试，不过调试过程中可能会用到一些gdb命令(比如忽略SIGSEGV错误)，需要好好熟悉下
