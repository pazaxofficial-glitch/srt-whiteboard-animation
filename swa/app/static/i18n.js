/* UI text in English and Persian. Add a language by adding another block. */
"use strict";

const I18N = {
  en: {
    "nav.projects": "Projects",
    "nav.hands": "Hands",
    "nav.backgrounds": "Boards",
    "nav.help": "Guide",
    "sys.noWhisper": "Whisper not found",
    "sys.noFfmpeg": "FFmpeg not found",

    "home.title": "Turn your narration into a hand-drawn video",
    "home.lead": "Upload the voice-over, paste your numbered script and drop in one image per line. The hand starts drawing each image the moment its line is spoken.",
    "home.new": "New video",
    "home.your": "Your videos",
    "home.none": "No projects yet. Create your first video.",
    "home.namePh": "Video name, e.g. The Spartan Way",

    "w.lines": "lines",
    "w.images": "images",
    "w.cancel": "Cancel",
    "w.create": "Create",
    "w.ok": "OK",
    "w.delete": "Delete",
    "w.next": "Next →",
    "w.back": "← Projects",
    "w.save": "Save",
    "w.builtin": "built-in",
    "w.image": "Image",
    "w.text": "Line",

    "st.rendered": "Rendered",
    "st.synced": "Synced",
    "st.draft": "Draft",
    "st.narrationOk": "Narration ✓",
    "st.noNarration": "No narration",
    "st.notSynced": "Not synced",
    "st.noHand": "No hand",

    "msg.saved": "Saved",
    "msg.saving": "Saving…",
    "msg.uploading": "Uploading…",
    "msg.needNarration": "Upload the narration first.",
    "msg.needScript": "Add the script first.",
    "msg.needImages": "Upload the images first.",
    "msg.estimating": "Whisper is not installed, so timings are estimated. Install Whisper for exact sync.",

    "p.openFolder": "Open folder",
    "p.deleteConfirm": "Delete this project and all its files?",
    "p.makeVideo": "Make video",

    "tab.content": "Narration & script",
    "tab.images": "Images",
    "tab.style": "Style",
    "tab.sync": "Sync",
    "tab.export": "Export",

    "job.starting": "Starting…",
    "job.align": "Syncing",
    "job.render": "Rendering",
    "job.eta": "left",
    "job.done.align": "Narration synced",
    "job.done.render": "Video ready",
    "job.cancelled": "Cancelled",
    "job.failed": "Failed",

    "c.narration": "Narration",
    "c.narrationHint": "The voice-over of the whole video. Its timing drives every drawing.",
    "c.replaceAudio": "Replace narration",
    "c.dropAudio": "Drop the narration here or click to choose",
    "c.script": "Script",
    "c.scriptHint": "One line per image. Number the lines (1. … 2. …) or just put each on its own line. Line 58 is drawn with image 58.",
    "c.scriptPh": "1. Life, the Spartan way.\n2. Every boy was given a shield and a spear.\n3. They trained every single day…",
    "c.parsed": "Detected lines",

    "i.title": "Images",
    "i.hint": "Name each image with its line number: 1.png, 2.jpg, 058.png… Upload them all at once, or as a ZIP. SVG line art is drawn stroke by stroke.",
    "i.drop": "Drop images or a ZIP here, or click to choose",
    "i.replace": "Replace all existing images",
    "i.noImage": "no image",
    "i.saved": "images saved",
    "i.skipped": "skipped",
    "i.missing": "Missing",
    "i.extra": "Images without a script line",
    "i.missingCount": "lines have no image",
    "i.allGood": "Every line has an image",
    "i.clear": "Remove all",
    "i.clearConfirm": "Remove all images from this project?",
    "i.noScript": "Add the script first to see which image goes with which line.",

    "bg.whiteboard": "Whiteboard",
    "bg.white": "Plain white",
    "bg.paper": "Paper",
    "bg.chalkboard": "Chalkboard",
    "bg.blackboard": "Blackboard",
    "bg.upload": "Upload board",
    "bg.lead": "The surface the hand draws on. On dark boards, dark lines turn into chalk automatically.",
    "bg.drop": "Drop a background image (it will fill the frame)",
    "bg.dark": "dark · chalk",

    "hands.upload": "Upload hand",
    "hands.lead": "Upload any hand holding a pen, marker or chalk as a transparent PNG, then click where the tip touches the board.",
    "hands.drop": "Drop a hand PNG here",
    "hands.dropHint": "Transparent background works best. The arm should run off the bottom edge.",
    "hands.tip": "Pen tip",
    "hands.deleteConfirm": "Delete this hand?",
    "hands.tipTitle": "Where does the pen touch the board?",
    "hands.tipHint": "Click the exact tip of the pen, marker or chalk.",
    "hands.name": "Name",
    "hands.size": "Size on screen",

    "s.board": "Board",
    "s.hand": "Hand",
    "s.handSize": "Hand size",
    "s.drawing": "Drawing",
    "s.colorMode": "Drawing style",
    "s.colorModeHint": "How each picture appears",
    "s.inkThenColor": "Outline, then colour",
    "s.colorStrokes": "Draw in colour",
    "s.inkOnly": "Line art only",
    "s.sync": "Pen rhythm",
    "s.syncHint": "Follow the voice: the pen moves while words are spoken",
    "s.speech": "Follow the voice",
    "s.linear": "Steady speed",
    "s.drawFill": "Drawing time",
    "s.drawFillHint": "Share of each line spent drawing; the rest shows the finished picture",
    "s.inkShare": "Outline vs. colour",
    "s.inkShareHint": "Share of drawing time used for the outline",
    "s.maxDraw": "Longest drawing",
    "s.maxDrawHint": "Cap for very long lines",
    "s.order": "Drawing order",
    "s.auto": "Auto",
    "s.ltr": "Left → right",
    "s.rtl": "Right → left",
    "s.ttb": "Top → bottom",
    "s.margin": "Image margin",
    "s.thickness": "SVG line thickness",
    "s.thicknessHint": "Only for SVG images",
    "s.transition": "Between images",
    "s.transitionType": "Transition",
    "s.slide": "Slide",
    "s.fade": "Fade",
    "s.wipe": "Wipe",
    "s.cut": "Cut",
    "s.transitionDur": "Duration",
    "s.video": "Video",
    "s.aspect": "Format",
    "s.resolution": "Resolution",
    "s.language": "Narration language",
    "s.languageHint": "Auto detects it from the script",
    "s.preview": "Preview",
    "s.previewHint": "A finished frame with your board and hand. Changes save automatically.",

    "y.title": "Sync the script to the voice",
    "y.hint": "Whisper listens to the narration and finds the exact moment every line begins. Your script stays the source of truth, so small recognition mistakes do not matter.",
    "y.whisper": "Most accurate. Runs on this computer.",
    "y.noWhisper": "Not installed. Run: pip install faster-whisper",
    "y.srt": "Import SRT",
    "y.srtHint": "Use subtitle timings you already have.",
    "y.estimate": "Estimate",
    "y.estimateHint": "Spread lines over the audio by length. Good for a quick draft.",
    "y.pickSrt": "Choose an SRT file first.",
    "y.model": "Model",
    "y.retranscribe": "Transcribe again",
    "y.run": "Sync now",
    "y.rerun": "Sync again",
    "y.timeline": "Timeline",
    "y.source": "Source",
    "y.duration": "Narration",
    "y.saveTimes": "Save times",
    "y.start": "Start (s)",
    "y.end": "End (s)",
    "y.play": "Play this line",
    "y.previewLine": "Preview this line",
    "y.previewOf": "Preview of line",

    "e.title": "Render the video",
    "e.render": "Render video",
    "e.high": "High quality",
    "e.draft": "Fast draft",
    "e.missingOk": "the previous drawing stays on screen",
    "e.notSynced": "Not synced yet — it will sync first.",
    "e.download": "Download",
    "e.deleteConfirm": "Delete this video file?",
    "e.videos": "Your renders",

    "help.html": `
      <h1>Guide</h1>
      <h2>Make a video in 5 steps</h2>
      <ol>
        <li><b>Narration & script</b> — upload the voice-over and paste the script, one line per image. Numbered lines (<code>1.</code>, <code>2)</code>, <code>[3]</code>) or plain lines both work.</li>
        <li><b>Images</b> — upload one image per line, named by line number: <code>1.png</code>, <code>2.png</code>, <code>058.jpg</code>. Several at once or a ZIP. Image 58 is drawn while line 58 is spoken.</li>
        <li><b>Style</b> — pick a board (whiteboard, white, paper, chalkboard, blackboard or your own), a hand, colours and transitions.</li>
        <li><b>Sync</b> — Whisper finds when each line starts. Fine-tune times in the table, play any line, or render a preview of a single line.</li>
        <li><b>Export</b> — render the MP4 with your narration.</li>
      </ol>
      <p>Or press <b>Make video</b> to sync and render in one click.</p>
      <h2>Best images</h2>
      <ul>
        <li>Clean line art on a plain white background draws most naturally.</li>
        <li>Transparent PNGs work too. Busy photos are drawn as a whole.</li>
        <li><b>SVG</b> line art is drawn exactly along its paths, stroke by stroke.</li>
      </ul>
      <h2>No image generator? Let Claude Code draw</h2>
      <p>Open the project folder in Claude Code and ask: <code>Draw the images for this project</code>. It reads <code>script.txt</code> and writes one SVG drawing per line into <code>images/</code> following the style guide in this app's <code>CLAUDE.md</code>.</p>
      <h2>Command line</h2>
      <pre class="code">python -m swa align "my-video"
python -m swa render "my-video" --line 12 --draft
python -m swa render "my-video"</pre>
      <h2>Where are my files?</h2>
      <p>Projects live in the <code>data/projects</code> folder next to the app. Use <b>Open folder</b> on a project.</p>`,
  },

  fa: {
    "nav.projects": "پروژه‌ها",
    "nav.hands": "دست‌ها",
    "nav.backgrounds": "تخته‌ها",
    "nav.help": "راهنما",
    "sys.noWhisper": "ویسپر پیدا نشد",
    "sys.noFfmpeg": "FFmpeg پیدا نشد",

    "home.title": "نریشن خودت را به ویدیوی دست‌کشیده تبدیل کن",
    "home.lead": "صدای نریشن را آپلود کن، اسکریپت شماره‌دار را بچسبان و برای هر خط یک تصویر بگذار. دست، هر تصویر را دقیقاً همان لحظه‌ای که خطش گفته می‌شود شروع به کشیدن می‌کند.",
    "home.new": "ویدیوی جدید",
    "home.your": "ویدیوهای شما",
    "home.none": "هنوز پروژه‌ای نساخته‌اید. اولین ویدیو را بسازید.",
    "home.namePh": "نام ویدیو، مثلاً زندگی به سبک اسپارتی",

    "w.lines": "خط",
    "w.images": "تصویر",
    "w.cancel": "انصراف",
    "w.create": "ساختن",
    "w.ok": "تأیید",
    "w.delete": "حذف",
    "w.next": "بعدی ←",
    "w.back": "→ پروژه‌ها",
    "w.save": "ذخیره",
    "w.builtin": "پیش‌فرض",
    "w.image": "تصویر",
    "w.text": "خط",

    "st.rendered": "ساخته شد",
    "st.synced": "همگام شد",
    "st.draft": "پیش‌نویس",
    "st.narrationOk": "نریشن ✓",
    "st.noNarration": "بدون نریشن",
    "st.notSynced": "همگام نشده",
    "st.noHand": "بدون دست",

    "msg.saved": "ذخیره شد",
    "msg.saving": "در حال ذخیره…",
    "msg.uploading": "در حال آپلود…",
    "msg.needNarration": "اول نریشن را آپلود کنید.",
    "msg.needScript": "اول اسکریپت را وارد کنید.",
    "msg.needImages": "اول تصویرها را آپلود کنید.",
    "msg.estimating": "ویسپر نصب نیست، پس زمان‌ها تخمینی هستند. برای همگام‌سازی دقیق ویسپر را نصب کنید.",

    "p.openFolder": "باز کردن پوشه",
    "p.deleteConfirm": "این پروژه و همه‌ی فایل‌هایش حذف شود؟",
    "p.makeVideo": "ساخت ویدیو",

    "tab.content": "نریشن و اسکریپت",
    "tab.images": "تصویرها",
    "tab.style": "ظاهر",
    "tab.sync": "همگام‌سازی",
    "tab.export": "خروجی",

    "job.starting": "در حال شروع…",
    "job.align": "همگام‌سازی",
    "job.render": "ساخت ویدیو",
    "job.eta": "مانده",
    "job.done.align": "نریشن همگام شد",
    "job.done.render": "ویدیو آماده است",
    "job.cancelled": "لغو شد",
    "job.failed": "خطا",

    "c.narration": "نریشن",
    "c.narrationHint": "صدای کل ویدیو. زمان‌بندی همه‌ی طراحی‌ها از روی همین صدا است.",
    "c.replaceAudio": "جایگزینی نریشن",
    "c.dropAudio": "فایل نریشن را اینجا بکشید یا کلیک کنید",
    "c.script": "اسکریپت",
    "c.scriptHint": "برای هر تصویر یک خط. خط‌ها را شماره بزنید (۱. … ۲. …) یا هر کدام را در یک سطر بنویسید. خط ۵۸ با تصویر ۵۸ کشیده می‌شود.",
    "c.scriptPh": "1. زندگی به سبک اسپارتی.\n2. به هر پسر یک سپر و یک نیزه می‌دادند.\n3. آن‌ها هر روز تمرین می‌کردند…",
    "c.parsed": "خط‌های شناسایی‌شده",

    "i.title": "تصویرها",
    "i.hint": "اسم هر تصویر را شماره‌ی خطش بگذارید: 1.png، 2.jpg، 058.png… همه را یک‌جا یا به‌صورت ZIP آپلود کنید. طرح‌های SVG خط به خط کشیده می‌شوند.",
    "i.drop": "تصویرها یا فایل ZIP را اینجا بکشید یا کلیک کنید",
    "i.replace": "جایگزینی همه‌ی تصویرهای قبلی",
    "i.noImage": "بدون تصویر",
    "i.saved": "تصویر ذخیره شد",
    "i.skipped": "رد شد",
    "i.missing": "ندارد",
    "i.extra": "تصویرهای بدون خط در اسکریپت",
    "i.missingCount": "خط بدون تصویر",
    "i.allGood": "همه‌ی خط‌ها تصویر دارند",
    "i.clear": "حذف همه",
    "i.clearConfirm": "همه‌ی تصویرهای این پروژه حذف شوند؟",
    "i.noScript": "اول اسکریپت را وارد کنید تا معلوم شود هر تصویر مال کدام خط است.",

    "bg.whiteboard": "وایت‌برد",
    "bg.white": "سفید ساده",
    "bg.paper": "کاغذ",
    "bg.chalkboard": "تخته سبز",
    "bg.blackboard": "تخته سیاه",
    "bg.upload": "آپلود تخته",
    "bg.lead": "سطحی که دست روی آن می‌کشد. روی تخته‌های تیره، خط‌های تیره خودکار به گچ تبدیل می‌شوند.",
    "bg.drop": "تصویر پس‌زمینه را اینجا بکشید (کل کادر را پر می‌کند)",
    "bg.dark": "تیره · گچی",

    "hands.upload": "آپلود دست",
    "hands.lead": "هر دستی که خودکار، ماژیک یا گچ گرفته را به‌صورت PNG با پس‌زمینه‌ی شفاف آپلود کنید و بعد روی نوک آن کلیک کنید.",
    "hands.drop": "فایل PNG دست را اینجا بکشید",
    "hands.dropHint": "پس‌زمینه‌ی شفاف بهترین نتیجه را می‌دهد. بهتر است ساعد تا لبه‌ی پایین تصویر ادامه داشته باشد.",
    "hands.tip": "نوک قلم",
    "hands.deleteConfirm": "این دست حذف شود؟",
    "hands.tipTitle": "قلم کجای تخته را لمس می‌کند؟",
    "hands.tipHint": "دقیقاً روی نوک خودکار، ماژیک یا گچ کلیک کنید.",
    "hands.name": "نام",
    "hands.size": "اندازه روی صفحه",

    "s.board": "تخته",
    "s.hand": "دست",
    "s.handSize": "اندازه‌ی دست",
    "s.drawing": "طراحی",
    "s.colorMode": "سبک کشیدن",
    "s.colorModeHint": "هر تصویر چطور ظاهر شود",
    "s.inkThenColor": "اول خط، بعد رنگ",
    "s.colorStrokes": "کشیدن رنگی",
    "s.inkOnly": "فقط خط",
    "s.sync": "ریتم قلم",
    "s.syncHint": "همراه صدا: قلم وقتی کلمات گفته می‌شوند حرکت می‌کند",
    "s.speech": "همراه صدا",
    "s.linear": "سرعت ثابت",
    "s.drawFill": "زمان کشیدن",
    "s.drawFillHint": "سهم هر خط که صرف کشیدن می‌شود؛ بقیه‌اش تصویر کامل نمایش داده می‌شود",
    "s.inkShare": "خط در برابر رنگ",
    "s.inkShareHint": "سهم زمان کشیدن که صرف خط‌ها می‌شود",
    "s.maxDraw": "بیشترین زمان کشیدن",
    "s.maxDrawHint": "سقف زمان برای خط‌های خیلی طولانی",
    "s.order": "ترتیب کشیدن",
    "s.auto": "خودکار",
    "s.ltr": "چپ ← راست",
    "s.rtl": "راست ← چپ",
    "s.ttb": "بالا ← پایین",
    "s.margin": "حاشیه‌ی تصویر",
    "s.thickness": "ضخامت خط SVG",
    "s.thicknessHint": "فقط برای تصویرهای SVG",
    "s.transition": "بین تصویرها",
    "s.transitionType": "نوع جابه‌جایی",
    "s.slide": "اسلاید",
    "s.fade": "محو",
    "s.wipe": "پاک کردن",
    "s.cut": "قطع",
    "s.transitionDur": "مدت",
    "s.video": "ویدیو",
    "s.aspect": "قالب",
    "s.resolution": "کیفیت",
    "s.language": "زبان نریشن",
    "s.languageHint": "حالت خودکار زبان را از اسکریپت تشخیص می‌دهد",
    "s.preview": "پیش‌نمایش",
    "s.previewHint": "یک فریم کامل با تخته و دست انتخابی. تغییرات خودکار ذخیره می‌شوند.",

    "y.title": "همگام‌سازی اسکریپت با صدا",
    "y.hint": "ویسپر به نریشن گوش می‌دهد و لحظه‌ی دقیق شروع هر خط را پیدا می‌کند. متن اسکریپت شما ملاک است، پس اشتباه‌های کوچک تشخیص گفتار مشکلی ایجاد نمی‌کند.",
    "y.whisper": "دقیق‌ترین روش. روی همین کامپیوتر اجرا می‌شود.",
    "y.noWhisper": "نصب نیست. اجرا کنید: pip install faster-whisper",
    "y.srt": "وارد کردن SRT",
    "y.srtHint": "از زمان‌بندی زیرنویسی که دارید استفاده کنید.",
    "y.estimate": "تخمینی",
    "y.estimateHint": "خط‌ها به نسبت طولشان روی صدا پخش می‌شوند. برای پیش‌نویس سریع.",
    "y.pickSrt": "اول فایل SRT را انتخاب کنید.",
    "y.model": "مدل",
    "y.retranscribe": "تبدیل دوباره‌ی گفتار",
    "y.run": "همگام کن",
    "y.rerun": "همگام‌سازی دوباره",
    "y.timeline": "جدول زمانی",
    "y.source": "منبع",
    "y.duration": "نریشن",
    "y.saveTimes": "ذخیره‌ی زمان‌ها",
    "y.start": "شروع (ثانیه)",
    "y.end": "پایان (ثانیه)",
    "y.play": "پخش این خط",
    "y.previewLine": "پیش‌نمایش این خط",
    "y.previewOf": "پیش‌نمایش خط",

    "e.title": "ساخت ویدیو",
    "e.render": "ساخت ویدیو",
    "e.high": "کیفیت بالا",
    "e.draft": "پیش‌نویس سریع",
    "e.missingOk": "تصویر قبلی روی صفحه می‌ماند",
    "e.notSynced": "هنوز همگام نشده؛ اول همگام می‌شود.",
    "e.download": "دانلود",
    "e.deleteConfirm": "این فایل ویدیو حذف شود؟",
    "e.videos": "ویدیوهای ساخته‌شده",

    "help.html": `
      <h1>راهنما</h1>
      <h2>ساخت ویدیو در ۵ مرحله</h2>
      <ol>
        <li><b>نریشن و اسکریپت</b>: صدای نریشن را آپلود کنید و اسکریپت را بچسبانید، هر خط برای یک تصویر. خط‌های شماره‌دار (<code>1.</code>، <code>2)</code>، <code>[3]</code>) یا خط‌های ساده هر دو قبول است.</li>
        <li><b>تصویرها</b>: برای هر خط یک تصویر با شماره‌ی همان خط آپلود کنید: <code>1.png</code>، <code>2.png</code>، <code>058.jpg</code>. چندتایی یا ZIP. تصویر ۵۸ وقتی خط ۵۸ گفته می‌شود کشیده می‌شود.</li>
        <li><b>ظاهر</b>: تخته (وایت‌برد، سفید، کاغذ، تخته سبز، تخته سیاه یا تصویر خودتان)، دست، رنگ و جابه‌جایی را انتخاب کنید.</li>
        <li><b>همگام‌سازی</b>: ویسپر شروع هر خط را پیدا می‌کند. زمان‌ها را در جدول دقیق کنید، هر خط را پخش کنید یا پیش‌نمایش یک خط را بسازید.</li>
        <li><b>خروجی</b>: فایل MP4 همراه با نریشن ساخته می‌شود.</li>
      </ol>
      <p>یا دکمه‌ی <b>ساخت ویدیو</b> را بزنید تا همگام‌سازی و ساخت با یک کلیک انجام شود.</p>
      <h2>بهترین تصویرها</h2>
      <ul>
        <li>طرح خطی تمیز روی پس‌زمینه‌ی سفید ساده طبیعی‌ترین نتیجه را می‌دهد.</li>
        <li>PNG شفاف هم کار می‌کند. عکس‌های شلوغ به‌صورت کامل کشیده می‌شوند.</li>
        <li>طرح‌های <b>SVG</b> دقیقاً روی مسیر خطوطشان، خط به خط کشیده می‌شوند.</li>
      </ul>
      <h2>تصویرساز ندارید؟ بگذارید Claude Code بکشد</h2>
      <p>پوشه‌ی پروژه را در Claude Code باز کنید و بنویسید: <code>Draw the images for this project</code>. فایل <code>script.txt</code> را می‌خواند و برای هر خط یک طرح SVG طبق راهنمای سبک در <code>CLAUDE.md</code> داخل پوشه‌ی <code>images/</code> می‌سازد.</p>
      <h2>خط فرمان</h2>
      <pre class="code" dir="ltr">python -m swa align "my-video"
python -m swa render "my-video" --line 12 --draft
python -m swa render "my-video"</pre>
      <h2>فایل‌ها کجا هستند؟</h2>
      <p>پروژه‌ها در پوشه‌ی <code>data/projects</code> کنار برنامه ذخیره می‌شوند. از دکمه‌ی <b>باز کردن پوشه</b> در هر پروژه استفاده کنید.</p>`,
  },
};

let CURRENT_LANG = "en";
function setLang(lang) { CURRENT_LANG = I18N[lang] ? lang : "en"; }
function getLang() { return CURRENT_LANG; }
function t(key) {
  const v = I18N[CURRENT_LANG][key];
  if (v !== undefined) return v;
  return I18N.en[key] !== undefined ? I18N.en[key] : key;
}
