---
title: Java动态代理
date: 2019-10-15 14:35:56
tags: [java, asm]
---


狭义的动态代理是指JVM提供的Proxy, 广义的是指能够在运行时动态更改类实现的手段(不过其核心原理大致都是手动拼接Class格式的二进制数据)。 原先博客中仅仅描述了Proxy这一项的用法， 此次更新扩展到其他类似ASM的动态代理手段, 主要描述以Hotspot的实现为主， 底层实现上Android的有些许不同. 
<!-- more  -->
# JDK自带的动态代理 &#x2013; Proxy

Proxy是JDK1.3之后自带的， 用于创建动态代理类与对象的机制. 创建的代理类的所有方法调用都会调用对应的InvocationHandler的invoke方法. 

使用起来比较简单: 

-   需要定义接口
-   Invocation Handler需要实现接口InvocationHandler, 实现invoke方法.
-   创建一个动态代理实例, 通过Proxy类

``` java
    import java.lang.reflect.InvocationHandler;
    import java.lang.reflect.Method;
    import java.lang.reflect.Proxy;
    import java.util.Arrays;
    
    public class ProxyDemo implements InvocationHandler{
    
    	interface ProxyInterface{
    		public String say(String world);
    	}
    
    	public static void main(String[] args){
    		ProxyInterface proxyInterface = (ProxyInterface) Proxy.newProxyInstance(ProxyDemo.class.getClassLoader(),
    				new Class[]{ProxyInterface.class}, new ProxyDemo());
    		String result = proxyInterface.say("Hello");
    		System.out.println("result is " + result);
    	}
    
    	@Override
    	public Object invoke(Object proxy, Method method, Object[] args) throws Throwable {
    		System.out.println("ProxyDemo: invoke(): " + method + ", args is " + Arrays.toString(args));
    		return "Complete";
    	}
    }
	```

运行后输出结果:
	```
    ProxyDemo: invoke(): public abstract java.lang.String ldk.learning.concurrency.ProxyDemo$ProxyInterface.say(java.lang.String), args is [Hello]
    result is Complete
	```

实际上就是根据interfaces生成一个Class对象, 然后反射newInstance而已, 真实实现是sun.misc.ProxyGenerator.java的generateClassFile
```java
    private byte[] generateClassFile(){
    	   ......
    	   /*
    		* Write all the items of the "ClassFile" structure.
    		* See JVMS section 4.1.
    		*/
    								   // u4 magic;
    	   dout.writeInt(0xCAFEBABE);
    								   // u2 minor_version;
    	   dout.writeShort(CLASSFILE_MINOR_VERSION);
    								   // u2 major_version;
    	   dout.writeShort(CLASSFILE_MAJOR_VERSION);
    
    	   cp.write(dout);             // (write constant pool)
    
    								   // u2 access_flags;
    	   dout.writeShort(accessFlags);
    								   // u2 this_class;
    	   dout.writeShort(cp.getClass(dotToSlash(className)));
    								   // u2 super_class;
    	   dout.writeShort(cp.getClass(superclassName));
    
    								   // u2 interfaces_count;
    	   dout.writeShort(interfaces.length);
    								   // u2 interfaces[interfaces_count];
    	   for (Class<?> intf : interfaces) {
    		   dout.writeShort(cp.getClass(
    			   dotToSlash(intf.getName())));
    	   }
    
    								   // u2 fields_count;
    	   dout.writeShort(fields.size());
    								   // field_info fields[fields_count];
    	   for (FieldInfo f : fields) {
    		   f.write(dout);
    	   }
    
    								   // u2 methods_count;
    	   dout.writeShort(methods.size());
    								   // method_info methods[methods_count];
    	   for (MethodInfo m : methods) {
    		   m.write(dout);
    	   }
    
    									// u2 attributes_count;
    	   dout.writeShort(0); // (no ClassFile attributes for proxy classes)
    	   ......
    }
```
没有什么神奇的地方, 根据Class文件格式，手动编织一个新类而已.  Android 在这里的实现上由于Class文件结构的不同， 没有在Java层编织新类， 而是提供了一个generateProxy的jni方法。


# 其他动态代理手段

由于[java Class文件格式](https://docs.oracle.com/javase/specs/jvms/se7/html/jvms-4.html)开源, 有很多第三方的动态代理的实现， 不过他们的原理大致都是根据配置生成新的Class文件， 然后交给ClassLoader取加载， 生成新的Class对象. 


## ASM

通用的java字节码改写与分析工具， 可以用来修改已有的类文件， 也可以用来动态生成类.  asm专注于性能, 一般用于编译器。 

-   Android中的字节码插桩, 如GrowingIO, 神策.
-   另外使用居多的是编译器, 如Groovy编译器， Kotlin编译器用于编译JVM平台语言.
-   测量单测覆盖率的Jacoco Codertura
-   CGLIB, class generate library, 用于动态生成代理对象, 用于单测框架与AOP编程

ASM的API主要由ClassReader, ClassWriter, ClassVisitor组成, 这里简单给个ClassWriter的实例代码
```java
    ClassWriter cw = new ClassWriter(0);
    FieldVisitor fv;
    MethodVisitor mv;
    AnnotationVisitor av0;
    
    cw.visit(V1_8, ACC_PUBLIC + ACC_SUPER, "ldk/learning/asm/dsuper/ExampleA", null, "java/lang/Object", null);
    
    {
    	mv = cw.visitMethod(ACC_PUBLIC, "<init>", "()V", null, null);
    	mv.visitCode();
    	mv.visitVarInsn(ALOAD, 0);
    	mv.visitMethodInsn(INVOKESPECIAL, "java/lang/Object", "<init>", "()V", false);
    	mv.visitInsn(RETURN);
    	mv.visitMaxs(1, 1);
    	mv.visitEnd();
    }
    {
    	mv = cw.visitMethod(ACC_PUBLIC + ACC_STATIC, "main", "([Ljava/lang/String;)V", null, null);
    	mv.visitCode();
    	mv.visitTypeInsn(NEW, "ldk/learning/asm/dsuper/ChildA");
    	mv.visitInsn(DUP);
    	mv.visitMethodInsn(INVOKESPECIAL, "ldk/learning/asm/dsuper/ChildA", "<init>", "()V", false);
    	mv.visitVarInsn(ASTORE, 1);
    	mv.visitVarInsn(ALOAD, 1);
    	mv.visitMethodInsn(INVOKESPECIAL, "ldk/learning/asm/dsuper/Parent", "loadUrl", "()V", false);
    	mv.visitInsn(RETURN);
    	mv.visitMaxs(2, 2);
    	mv.visitEnd();
    }
    cw.visitEnd();
    
    byte[] newClassByte = cw.toByteArray();
    File file = new File("ExampleA.class");
    OutputStream outputStream = new FileOutputStream(file);
    outputStream.write(newClassByte);
    outputStream.flush();
    outputStream.close();
```
推荐一个ASM的Intelli插件[ASM Bytecode Outline](https://plugins.jetbrains.com/plugin/5918-asm-bytecode-outline) 可以方便的查看字节码与对应的ASM方法. 


## Javaassist

Javassist(JAVA programming ASSISTANT)是区别与asm的另一个字节码修改与生成的工具, 属于jboss社区. 有别与asm的是， 其提供了两套API, 基于源代码级别的与基于字节码级别的API. 

由于没有使用Javassist的， 具体demo与源码后续使用后再补充吧. 


## Java poiet

提到源代码级别的字节码修改工具， 可能要提下Java poiet这个类库， 它不是用来进行字节码操控的， 而是用来生成.java文件的， 想来用来自动生成代码是很好的。 
