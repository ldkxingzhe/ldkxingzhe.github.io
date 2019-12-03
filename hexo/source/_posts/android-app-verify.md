---
title: Android Applink校验过程
date: 2019-12-03 14:09:09
tags: [android, applink]
---
探究Applink的校验过程
<!-- more  -->

实际上就是IntentFilter的校验, 对应的Intent的Action值为 ACTION\_INTENT\_FILTER\_NEEDS\_VERIFICATION="android.intent.action.INTENT\_FILTER\_NEEDS\_VERIFICATION"

有两处使用的位置(一个接收处, 一个发送处):

-   PackageManagerService.java: 1. 启动时根据Action获取mIntentFilterVerifierComponent值; 2. sendVerificationRequest用于发送验证请求
-   StatementService服务中, IntentFilterrVerificationReceiver中用于过滤Intent

两者传参值:

-   URI\_SCHEME("android.content.pm.extra.INTENT\_FILTER\_VERIFICATION\_URI\_SCHEME"): url scheme的类型, 类型为String, 一般是https
-   HOSTS("android.content.pm.extra.INTENT\_FILTER\_VERIFICATION\_HOSTS"): 需要验证的Hosts，类型为String, 多个String之间用" "分割, 每个App限制Host数量为10个(一次请求)
-   PACKAGE\_NAME("android.content.pm.extra.INTENT\_FILTER\_VERIFICATION\_PACKAGE\_NAME"): 需要验证的包名, 类型String

调用adb shell dumpsys package d打印的信息是由PackageManagerService的dump方法处理的, d表示 domain-preferrred-apps. 打印代码如下: 
	
	```java
    final String prefix = "  ";
    Collection<PackageSetting> allPackageSettings = mSettings.mPackages.values();
    if (allPackageSettings.size() == 0) {
    	pw.println("No domain preferred apps!");
    	pw.println();
    } else {
    	pw.println("App verification status:");
    	pw.println();
    	count = 0;
    	for (PackageSetting ps : allPackageSettings) {
    		IntentFilterVerificationInfo ivi = ps.getIntentFilterVerificationInfo();
    		if (ivi == null || ivi.getPackageName() == null) continue;
    		pw.println(prefix + "Package: " + ivi.getPackageName());
    		pw.println(prefix + "Domains: " + ivi.getDomainsString());
    		pw.println(prefix + "Status:  " + ivi.getStatusString());
    		pw.println();
    		count++;
    	}
    	if (count == 0) {
    		pw.println(prefix + "No app verification established.");
    		pw.println();
    	}
    	for (int userId : sUserManager.getUserIds()) {
    		pw.println("App linkages for user " + userId + ":");
    		pw.println();
    		count = 0;
    		for (PackageSetting ps : allPackageSettings) {
    			final long status = ps.getDomainVerificationStatusForUser(userId);
    			if (status >> 32 == INTENT_FILTER_DOMAIN_VERIFICATION_STATUS_UNDEFINED
    					&& !DEBUG_DOMAIN_VERIFICATION) {
    				continue;
    			}
    			pw.println(prefix + "Package: " + ps.name);
    			pw.println(prefix + "Domains: " + dumpDomainString(ps.name));
    			String statusStr = IntentFilterVerificationInfo.
    					getStatusStringFromValue(status);
    			pw.println(prefix + "Status:  " + statusStr);
    			pw.println();
    			count++;
    		}
    		if (count == 0) {
    			pw.println(prefix + "No configured app linkages.");
    			pw.println();
    		}
    	}
    }
	```
可以发现每个安装包Package都有一个IntentFilterVerificationInfo的对象, status状态有一下几种: 

-   always: 表示该App是该链接的默认App, 即使有两个App拥有相同的授权host, 也不会弹出选择App的对话框, 代表校验成功
-   ask: 表示如果有两个应用host, path验证通过, 系统会弹出对话框供用户选择, 代表校验失败
-   never: Applink永远不会打开该App
-   always-ask: always与ask的混合体, 即时某个App的状态是always, 其也会作为选择的一部分(没见过这种状态)
-   undefined: 初始值， 仅表示未校验完成.

从源代码验证文档细节, PackageManagerService.filterCandidatesWithDomainPreferredActivitiesLPr:

-   第一步: 收集always, undefined, alwaysAsk, never, matchAll(表示浏览器)各种状态的列表
-   第二步: 如果always候选人存在, 则结果中放置全部的always候选人, 不包含浏览器
-   第二步: 如果always候选人不存在, 则将undefined的列表(ask与undefined行为一致)放置在候选人中, 并且包含浏览器
-   第三步: 如果存在always-ask状态的候选人, 将其也放在候选人列表中, 后续包含浏览器
	```java
    private List<ResolveInfo> filterCandidatesWithDomainPreferredActivitiesLPr(Intent intent,
    		int matchFlags, List<ResolveInfo> candidates, CrossProfileDomainInfo xpDomainInfo,
    		int userId) {
    	final boolean debug = (intent.getFlags() & Intent.FLAG_DEBUG_LOG_RESOLUTION) != 0;
    
    	if (DEBUG_PREFERRED || DEBUG_DOMAIN_VERIFICATION) {
    		Slog.v(TAG, "Filtering results with preferred activities. Candidates count: " +
    				candidates.size());
    	}
    
    	ArrayList<ResolveInfo> result = new ArrayList<ResolveInfo>();
    	ArrayList<ResolveInfo> alwaysList = new ArrayList<ResolveInfo>();
    	ArrayList<ResolveInfo> undefinedList = new ArrayList<ResolveInfo>();
    	ArrayList<ResolveInfo> alwaysAskList = new ArrayList<ResolveInfo>();
    	ArrayList<ResolveInfo> neverList = new ArrayList<ResolveInfo>();
    	ArrayList<ResolveInfo> matchAllList = new ArrayList<ResolveInfo>();
    
    	synchronized (mPackages) {
    		final int count = candidates.size();
    		// First, try to use linked apps. Partition the candidates into four lists:
    		// one for the final results, one for the "do not use ever", one for "undefined status"
    		// and finally one for "browser app type".
    		for (int n=0; n<count; n++) {
    			ResolveInfo info = candidates.get(n);
    			String packageName = info.activityInfo.packageName;
    			PackageSetting ps = mSettings.mPackages.get(packageName);
    			if (ps != null) {
    				// Add to the special match all list (Browser use case)
    				if (info.handleAllWebDataURI) {
    					matchAllList.add(info);
    					continue;
    				}
    				// Try to get the status from User settings first
    				long packedStatus = getDomainVerificationStatusLPr(ps, userId);
    				int status = (int)(packedStatus >> 32);
    				int linkGeneration = (int)(packedStatus & 0xFFFFFFFF);
    				if (status == INTENT_FILTER_DOMAIN_VERIFICATION_STATUS_ALWAYS) {
    					if (DEBUG_DOMAIN_VERIFICATION || debug) {
    						Slog.i(TAG, "  + always: " + info.activityInfo.packageName
    								+ " : linkgen=" + linkGeneration);
    					}
    					// Use link-enabled generation as preferredOrder, i.e.
    					// prefer newly-enabled over earlier-enabled.
    					info.preferredOrder = linkGeneration;
    					alwaysList.add(info);
    				} else if (status == INTENT_FILTER_DOMAIN_VERIFICATION_STATUS_NEVER) {
    					if (DEBUG_DOMAIN_VERIFICATION || debug) {
    						Slog.i(TAG, "  + never: " + info.activityInfo.packageName);
    					}
    					neverList.add(info);
    				} else if (status == INTENT_FILTER_DOMAIN_VERIFICATION_STATUS_ALWAYS_ASK) {
    					if (DEBUG_DOMAIN_VERIFICATION || debug) {
    						Slog.i(TAG, "  + always-ask: " + info.activityInfo.packageName);
    					}
    					alwaysAskList.add(info);
    				} else if (status == INTENT_FILTER_DOMAIN_VERIFICATION_STATUS_UNDEFINED ||
    						status == INTENT_FILTER_DOMAIN_VERIFICATION_STATUS_ASK) {
    					if (DEBUG_DOMAIN_VERIFICATION || debug) {
    						Slog.i(TAG, "  + ask: " + info.activityInfo.packageName);
    					}
    					undefinedList.add(info);
    				}
    			}
    		}
    
    		// We'll want to include browser possibilities in a few cases
    		boolean includeBrowser = false;
    
    		// First try to add the "always" resolution(s) for the current user, if any
    		if (alwaysList.size() > 0) {
    			result.addAll(alwaysList);
    		} else {
    			// Add all undefined apps as we want them to appear in the disambiguation dialog.
    			result.addAll(undefinedList);
    			// Maybe add one for the other profile.
    			if (xpDomainInfo != null && (
    					xpDomainInfo.bestDomainVerificationStatus
    					!= INTENT_FILTER_DOMAIN_VERIFICATION_STATUS_NEVER)) {
    				result.add(xpDomainInfo.resolveInfo);
    			}
    			includeBrowser = true;
    		}
    
    		// The presence of any 'always ask' alternatives means we'll also offer browsers.
    		// If there were 'always' entries their preferred order has been set, so we also
    		// back that off to make the alternatives equivalent
    		if (alwaysAskList.size() > 0) {
    			for (ResolveInfo i : result) {
    				i.preferredOrder = 0;
    			}
    			result.addAll(alwaysAskList);
    			includeBrowser = true;
    		}
    
    		if (includeBrowser) {
    			// Also add browsers (all of them or only the default one)
    			if (DEBUG_DOMAIN_VERIFICATION) {
    				Slog.v(TAG, "   ...including browsers in candidate set");
    			}
    			if ((matchFlags & MATCH_ALL) != 0) {
    				result.addAll(matchAllList);
    			} else {
    				// Browser/generic handling case.  If there's a default browser, go straight
    				// to that (but only if there is no other higher-priority match).
    				final String defaultBrowserPackageName = getDefaultBrowserPackageName(userId);
    				int maxMatchPrio = 0;
    				ResolveInfo defaultBrowserMatch = null;
    				final int numCandidates = matchAllList.size();
    				for (int n = 0; n < numCandidates; n++) {
    					ResolveInfo info = matchAllList.get(n);
    					// track the highest overall match priority...
    					if (info.priority > maxMatchPrio) {
    						maxMatchPrio = info.priority;
    					}
    					// ...and the highest-priority default browser match
    					if (info.activityInfo.packageName.equals(defaultBrowserPackageName)) {
    						if (defaultBrowserMatch == null
    								|| (defaultBrowserMatch.priority < info.priority)) {
    							if (debug) {
    								Slog.v(TAG, "Considering default browser match " + info);
    							}
    							defaultBrowserMatch = info;
    						}
    					}
    				}
    				if (defaultBrowserMatch != null
    						&& defaultBrowserMatch.priority >= maxMatchPrio
    						&& !TextUtils.isEmpty(defaultBrowserPackageName))
    				{
    					if (debug) {
    						Slog.v(TAG, "Default browser match " + defaultBrowserMatch);
    					}
    					result.add(defaultBrowserMatch);
    				} else {
    					result.addAll(matchAllList);
    				}
    			}
    
    			// If there is nothing selected, add all candidates and remove the ones that the user
    			// has explicitly put into the INTENT_FILTER_DOMAIN_VERIFICATION_STATUS_NEVER state
    			if (result.size() == 0) {
    				result.addAll(candidates);
    				result.removeAll(neverList);
    			}
    		}
    	}
    	if (DEBUG_PREFERRED || DEBUG_DOMAIN_VERIFICATION) {
    		Slog.v(TAG, "Filtered results with preferred activities. New candidates count: " +
    				result.size());
    		for (ResolveInfo info : result) {
    			Slog.v(TAG, "  + " + info.activityInfo);
    		}
    	}
    	return result;
    }
	```
注意校验过程中的签名获取: 
	
	```java
    /**
     * Returns the normalized sha-256 fingerprints of a given package according to the Android
     * package manager.
     */
    public static List<String> getCertFingerprintsFromPackageManager(String packageName,
    		Context context) throws NameNotFoundException {
    	Signature[] signatures = context.getPackageManager().getPackageInfo(packageName,
    			PackageManager.GET_SIGNATURES).signatures;
    	ArrayList<String> result = new ArrayList<String>(signatures.length);
    	for (Signature sig : signatures) {
    		result.add(computeNormalizedSha256Fingerprint(sig.toByteArray()));
    	}
    	return result;
    }
	```

**另外需要注意的是:** 
AOSP中Intent Filter Verifier: 

	```sh
    $ adb shell dumpsys package i
    Intent Filter Verifier:
      Using: com.android.statementservice (uid=10048)
	```

使用Google Play Service的Intent Filter Verifier: 
	
	```sh
    $ adb shell dumpsys package i
    Intent Filter Verifier:
      Using: com.google.android.gms (uid=10028)
	```

我们用来分析的是开源的statementservice, 在statementservice并不校验Google Console。 但是gms是需要校验Google Console的, 请参见官方文档 "to verify ownership through Google Search Console"
