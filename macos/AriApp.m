#import <AppKit/AppKit.h>
#import <WebKit/WebKit.h>

@interface AriAppDelegate : NSObject <NSApplicationDelegate, WKNavigationDelegate>
@property(nonatomic, strong) NSWindow *window;
@property(nonatomic, strong) WKWebView *webView;
@property(nonatomic, strong) NSTask *serverTask;
@property(nonatomic, strong) NSFileHandle *serverLog;
@property(nonatomic, copy) NSString *port;
@end

@implementation AriAppDelegate

- (void)applicationDidFinishLaunching:(NSNotification *)notification {
  self.port = NSProcessInfo.processInfo.environment[@"ARI_PORT"] ?: NSProcessInfo.processInfo.environment[@"KYN_PORT"] ?: @"8765";
  [self installMenu];
  [self createWindow];
  [self.window makeKeyAndOrderFront:nil];
  [NSApp activateIgnoringOtherApps:YES];
  [self checkHealth:^(BOOL healthy) {
    if (healthy) {
      [self loadApp];
    } else {
      [self launchServer];
      [self waitForServer:0];
    }
  }];
}

- (BOOL)applicationShouldTerminateAfterLastWindowClosed:(NSApplication *)sender {
  return YES;
}

- (NSURL *)appURL {
  return [NSURL URLWithString:[NSString stringWithFormat:@"http://127.0.0.1:%@/app/?desktop=1#setup", self.port]];
}

- (NSURL *)healthURL {
  return [NSURL URLWithString:[NSString stringWithFormat:@"http://127.0.0.1:%@/api/health", self.port]];
}

- (void)installMenu {
  NSMenu *menu = [[NSMenu alloc] init];
  NSMenuItem *root = [[NSMenuItem alloc] init];
  NSMenu *appMenu = [[NSMenu alloc] init];
  root.title = @"Ari";
  [appMenu addItemWithTitle:@"About Ari" action:@selector(orderFrontStandardAboutPanel:) keyEquivalent:@""];
  [appMenu addItem:NSMenuItem.separatorItem];
  [appMenu addItemWithTitle:@"Quit Ari" action:@selector(terminate:) keyEquivalent:@"q"];
  root.submenu = appMenu;
  [menu addItem:root];
  NSApp.mainMenu = menu;
}

- (void)createWindow {
  NSRect frame = NSMakeRect(0, 0, 1120, 820);
  self.window = [[NSWindow alloc] initWithContentRect:frame
                                           styleMask:NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskMiniaturizable | NSWindowStyleMaskResizable
                                             backing:NSBackingStoreBuffered
                                               defer:NO];
  self.window.title = @"Ari";
  self.window.minSize = NSMakeSize(700, 560);
  [self.window center];
  [self.window setFrameAutosaveName:@"AriMainWindow"];

  WKWebViewConfiguration *configuration = [[WKWebViewConfiguration alloc] init];
  self.webView = [[WKWebView alloc] initWithFrame:NSZeroRect configuration:configuration];
  self.webView.navigationDelegate = self;
  self.webView.allowsBackForwardNavigationGestures = YES;
  self.webView.underPageBackgroundColor = NSColor.windowBackgroundColor;
  self.window.contentView = self.webView;
}

- (void)checkHealth:(void (^)(BOOL healthy))completion {
  NSMutableURLRequest *request = [NSMutableURLRequest requestWithURL:self.healthURL];
  request.HTTPMethod = @"GET";
  request.timeoutInterval = 1.5;
  [[[NSURLSession sharedSession] dataTaskWithRequest:request completionHandler:^(NSData *data, NSURLResponse *response, NSError *error) {
    BOOL healthy = [response isKindOfClass:NSHTTPURLResponse.class] && ((NSHTTPURLResponse *)response).statusCode == 200;
    dispatch_async(dispatch_get_main_queue(), ^{ completion(healthy); });
  }] resume];
}

- (void)launchServer {
  if (self.serverTask) return;
  NSURL *serverURL = [NSBundle.mainBundle.resourceURL URLByAppendingPathComponent:@"AriServer"];
  if (![NSFileManager.defaultManager isExecutableFileAtPath:serverURL.path]) {
    [self showFailure:@"Ari could not find its bundled local service."];
    return;
  }

  NSString *logDirectory = [NSHomeDirectory() stringByAppendingPathComponent:@"Library/Logs/Ari"];
  NSString *logPath = [logDirectory stringByAppendingPathComponent:@"desktop-server.log"];
  NSError *fileError = nil;
  [NSFileManager.defaultManager createDirectoryAtPath:logDirectory withIntermediateDirectories:YES attributes:nil error:&fileError];
  if (fileError) {
    [self showFailure:[NSString stringWithFormat:@"Ari could not create its local log: %@", fileError.localizedDescription]];
    return;
  }
  if (![NSFileManager.defaultManager fileExistsAtPath:logPath]) {
    [NSFileManager.defaultManager createFileAtPath:logPath contents:[NSData data] attributes:nil];
  }
  self.serverLog = [NSFileHandle fileHandleForWritingAtPath:logPath];
  [self.serverLog seekToEndOfFile];

  NSTask *task = [[NSTask alloc] init];
  task.executableURL = serverURL;
  NSMutableDictionary *environment = [NSProcessInfo.processInfo.environment mutableCopy];
  NSString *home = NSHomeDirectory();
  environment[@"PATH"] = [NSString stringWithFormat:@"%@/.local/bin:%@/.opencode/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin", home, home];
  environment[@"KYN_HOST"] = @"127.0.0.1";
  environment[@"KYN_PORT"] = self.port;
  environment[@"KYN_CONTROL_URL"] = [NSString stringWithFormat:@"http://127.0.0.1:%@", self.port];
  task.environment = environment;
  task.standardOutput = self.serverLog;
  task.standardError = self.serverLog;
  NSError *launchError = nil;
  if (![task launchAndReturnError:&launchError]) {
    [self showFailure:[NSString stringWithFormat:@"Ari could not start its local service: %@", launchError.localizedDescription]];
    return;
  }
  self.serverTask = task;
}

- (void)waitForServer:(NSUInteger)attempt {
  [self checkHealth:^(BOOL healthy) {
    if (healthy) {
      [self loadApp];
    } else if (attempt < 60) {
      dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(NSEC_PER_SEC / 2)), dispatch_get_main_queue(), ^{
        [self waitForServer:attempt + 1];
      });
    } else {
      [self showFailure:@"Ari’s local service did not start. Check ~/Library/Logs/Ari/desktop-server.log, then quit and reopen Ari."];
    }
  }];
}

- (void)loadApp {
  [self.webView loadRequest:[NSURLRequest requestWithURL:self.appURL]];
}

- (void)showFailure:(NSString *)message {
  NSString *escaped = [[message stringByReplacingOccurrencesOfString:@"&" withString:@"&amp;"] stringByReplacingOccurrencesOfString:@"<" withString:@"&lt;"];
  escaped = [escaped stringByReplacingOccurrencesOfString:@">" withString:@"&gt;"];
  NSString *html = [NSString stringWithFormat:@"<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width'><style>body{font:16px -apple-system,BlinkMacSystemFont,sans-serif;background:#f6f7f4;color:#172018;margin:0;padding:56px;line-height:1.6}main{max-width:680px;margin:auto}h1{font-size:32px;letter-spacing:-.04em}p{color:#606961}</style><main><h1>Ari couldn’t start</h1><p>%@</p></main>", escaped];
  [self.webView loadHTMLString:html baseURL:nil];
}

- (void)webView:(WKWebView *)webView decidePolicyForNavigationAction:(WKNavigationAction *)action decisionHandler:(void (^)(WKNavigationActionPolicy))decisionHandler {
  NSURL *url = action.request.URL;
  if ([url.host isEqualToString:@"127.0.0.1"] && url.port.integerValue == self.port.integerValue) {
    decisionHandler(WKNavigationActionPolicyAllow);
  } else if (action.navigationType == WKNavigationTypeLinkActivated && ([url.scheme isEqualToString:@"https"] || [url.scheme isEqualToString:@"http"])) {
    [NSWorkspace.sharedWorkspace openURL:url];
    decisionHandler(WKNavigationActionPolicyCancel);
  } else {
    decisionHandler(WKNavigationActionPolicyCancel);
  }
}

@end

int main(int argc, const char *argv[]) {
  @autoreleasepool {
    NSApplication *application = NSApplication.sharedApplication;
    AriAppDelegate *delegate = [[AriAppDelegate alloc] init];
    application.delegate = delegate;
    application.activationPolicy = NSApplicationActivationPolicyRegular;
    [application run];
  }
  return 0;
}
