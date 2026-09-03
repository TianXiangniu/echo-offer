## `npm run test:profile-weak-points`

```text
> test:profile-weak-points
> node --experimental-strip-types lib/profile-weak-points.test.ts

(node:71128) [MODULE_TYPELESS_PACKAGE_JSON] Warning: Module type of file:///C:/Users/%E6%B5%B7%E9%98%94%E5%A4%A9%E7%A9%BA/Desktop/Echo%20Offer/frontend/lib/profile-weak-points.test.ts is not specified and it doesn't parse as CommonJS.
Reparsing as ES module because module syntax was detected. This incurs a performance overhead.
To eliminate this warning, add "type": "module" to C:\Users\海阔天空\Desktop\Echo Offer\frontend\package.json.
(Use `node --trace-warnings ...` to show where the warning was created)
profile weak points contract tests passed
```

## `npm run build`

```text
> build
> next build

   ▲ Next.js 15.5.23
   - Environments: .env.local

   Creating an optimized production build ...
 ✓ Compiled successfully in 2.7s
   Linting and checking validity of types ...
   Collecting page data ...
   Generating static pages (0/7) ...
   Generating static pages (1/7) 
   Generating static pages (3/7) 
   Generating static pages (5/7) 
 ✓ Generating static pages (7/7)
   Finalizing page optimization ...
   Collecting build traces ...

Route (app)                                 Size  First Load JS
┌ ○ /                                    7.69 kB         110 kB
├ ○ /_not-found                            997 B         104 kB
├ ○ /console                             4.48 kB         107 kB
├ ○ /history                             3.71 kB         106 kB
├ ƒ /interview/[id]                      6.73 kB         109 kB
├ ○ /profile                             5.88 kB         108 kB
└ ƒ /report/[id]                         7.73 kB         110 kB
+ First Load JS shared by all             103 kB
  ├ chunks/493-a9bce8b61dc17c96.js       46.4 kB
  ├ chunks/4bd1b696-c023c6e3521b1417.js  54.2 kB
  └ other shared chunks (total)          1.99 kB

○  (Static)   prerendered as static content
ƒ  (Dynamic)  server-rendered on demand
```
