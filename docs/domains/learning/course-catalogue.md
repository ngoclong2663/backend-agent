# Learning: course catalogue (self-paced)

A catalogue of self-paced courses. A learner browses, enrolls, follows ordered lessons and picks up where they left
off. Instructors build courses in a studio. Admins curate categories and can unpublish a course.

## Studied

- Udemy: open marketplace of paid self-paced video courses.
- Coursera: university and company courses with graded quizzes and certificates.
- Skillshare: subscription catalogue of short project-based classes.
- LinkedIn Learning: professional skills library with learning paths.
- Khan Academy: free lessons with practice exercises and mastery progress.
- Domestika: creative courses split into units with a final project.
- edX: university courses with a syllabus, quizzes and a discussion forum.

## People and areas

| Role | Area | First device |
|---|---|---|
| Learner | Learners (browse, learn) | Mobile-first, works on desktop |
| Instructor | Studio (build courses, answer questions) | Desktop |
| Admin | Admin (categories, course moderation) | Desktop |

## Pages

### Learners

| Page | Reached by | Sections in order | Actions |
|---|---|---|---|
| Home | Menu tab "Home" | `resume-card`: the last lesson (course title, lesson title, cover media, progress) · `card-row` "My courses": enrolled courses (cover, title, `progress-bar`) · `card-row` per category: courses (cover, title, instructor, rating, price or "Free") | Resume, open a course, see all of a category |
| Browse | Menu tab "Browse" | `search-bar`: course title, instructor · `filter-bar`: category, level, duration, price, rating · `card-grid`: courses (cover, title, instructor, rating, reviewCount, level, price) | Search, filter, open a course |
| Category | Link from a home row or Browse filter | `record-header`: category name, course count · `filter-bar`: level, sort (popular, newest, rating) · `card-grid`: courses | Filter, open a course |
| Course | Card in any list | `record-header`: title, summary, instructor, rating, reviewCount, learner count, level, duration · `media`: cover or preview video · `cta-panel`: price or Free, Enroll; once enrolled, Continue with progress · `highlights`: what you'll learn · `curriculum`: sections with ordered lessons (title, duration, kind: video or text, lock state before enrolling, a free preview flag) · `author-card`: instructor (name, bio, course count) · `review-list`: rating summary, newest reviews | Enroll, Continue, preview a lesson, open a lesson (enrolled), read all reviews |
| Lesson | Resume, a curriculum row, Next lesson | `lesson-player`: the video or written body, duration · `action-bar`: Mark complete (toggle with state), Next lesson · `curriculum`: the course's lessons beside the player on desktop, in a drawer on phone (done ticks, current marker) · `progress-bar`: course progress · `quiz`: when the lesson ends with one (start, questions, submit, score, pass mark, answers after submitting) · `comment-thread`: questions under the lesson (author, text, time, replies, the instructor's answer marked) | Mark complete, next lesson, open another lesson, take the quiz, ask, reply |
| My learning | Menu tab "My learning" | `tab-strip`: In progress, Completed · `card-list`: enrolled courses (cover, title, `progress-bar`, lastLesson, Resume) | Resume a course, open a course |
| Rate course | Button "Rate" on a completed course, or the end of the last lesson | `form`: stars, short review | Submit, skip |
| Profile | Menu tab "Account" | `profile-header`: name, avatar, courses completed · `form`: name, email, password | Edit, sign out |

### Studio (instructors)

| Page | Reached by | Sections in order | Actions |
|---|---|---|---|
| My courses | Menu "Courses" (home) | `data-table`: courses (title, `status-pill`: draft or published, learners, rating, updated) | New course, open a course |
| Course editor | Row in My courses | `form`: title, summary, cover, category, level, price · `curriculum`: sections and lessons in order, editable (add, reorder, rename) · `workflow-bar`: draft or published | Save, add lesson, reorder, publish, unpublish |
| Lesson editor | "Add lesson" or a lesson row | `form`: title, kind (video or text), body or video upload (`media-upload`), duration · `quiz`: questions with choices and the right answer, pass mark | Save, add question, delete |
| Questions | Menu "Q&A" | `filter-bar`: course, unanswered first · `card-list`: questions (lesson, learner, text, reply count) · `comment-thread`: the selected question's replies | Reply, mark as answered |
| Reviews | Menu "Reviews" | `kpi-row`: average rating, review count · `review-list`: reviews per course | Filter by course |

### Admin

| Page | Reached by | Sections in order | Actions |
|---|---|---|---|
| Courses | Menu "Courses" | `filter-bar`: status, category · `data-table`: courses (title, instructor, `status-pill`, learners, rating) | Unpublish, republish, open |
| Categories | Menu "Categories" | `data-table`: categories (name, course count, order) | Add, rename, reorder, delete when empty |

## Main tasks

| Task | Role | Path (click by click) | Clicks | Budget |
|---|---|---|---|---|
| resume-lesson: resume the last lesson from home | Learner | Home: Resume on the `resume-card` | 1 | 1 |
| see-progress: see progress per course | Learner | Home: the "My courses" row shows each progress bar; or menu "My learning" | 0 (1 for the full list) | 1 |
| complete-lesson: mark a lesson complete | Learner | Home: Resume (1), Mark complete (2) | 2 | 2 |
| answer-question: reply to a question under a lesson | Learner | Home: Resume (1), Reply on a question under the lesson (2), type, Post (3) | 3 | 3 |
| submit-quiz: submit a quiz | Learner | Home: Resume (1) on a lesson with a quiz, Start quiz (2), choose answers, Submit (3) | 3 | 4 |
| Enroll in a course | Learner | Browse (1), a course card (2), Enroll (3); a free course opens its first lesson | 3 | 3 |
| Rate a finished course | Learner | My learning (1), Completed tab (2), Rate (3), pick stars, Submit (4) | 4 | 4 |
| Add a lesson to a course | Instructor | My courses: a course row (1), Add lesson (2), fill title and body, Save (3) | 3 | 3 |
| Unpublish a course | Admin | Courses: Unpublish on its row (1), confirm (2) | 2 | 2 |

## Data the pages need

- Course card: `title`, `cover`, `instructorName`, `rating`*, `reviewCount`*, `level`, `price` or free, `durationTotal`*.
- Course page: the card's fields plus `summary`, `highlights`, `learnerCount`*, `enrolledByMe`*, `progress`*,
  and `curriculum`: sections with lessons (`title`, `kind`, `duration`, `position`, `isPreview`, `doneByMe`*).
- Resume card and My learning: `lastLesson`* (course, lesson title, position), `progress`* (share of lessons done),
  `completedAt`*.
- Lesson: `title`, `kind`, `videoUrl` or `body`, `duration`, `doneByMe`*, `nextLesson`*, `previousLesson`*,
  the quiz (`questions`, `choices`, `passMark`) and, after submitting, `score`*, `passed`*, the right answers.
- Questions: `author`, `text`, `createdAt`, `replies`, `replyCount`*, `isInstructor`* on each reply.
- Reviews: `stars`, `text`, `author`, `createdAt`; `rating`* and `reviewCount`* on the course.
- Studio: `status`, `learnerCount`*, `rating`*, `unansweredCount`*.

\* computed by the server. `progress`, `lastLesson` and `doneByMe` come from the enrollment feature, `rating` and
`reviewCount` from reviews. The client never sends them.

## States

- Home with no enrollment: no `resume-card`; the first row becomes "Start learning" with popular courses.
- Course not enrolled: lessons show a lock except preview lessons; the player is not reachable by URL.
- Lesson load: the player reserves its size while loading; the curriculum stays visible.
- Last lesson done: Next lesson becomes "Finish course", then the rating prompt; progress reaches 100%.
- Quiz failed: score and pass mark shown, the right answers shown, Retry offered.
- Empty search: say nothing matched and show the categories instead.
- Error saving progress: keep the done tick, retry quietly, show a small notice only if it fails twice.

## Never shown to

- Learners: draft or unpublished courses, other learners' progress and scores, quiz answers before submitting,
  the studio and admin menus, revenue.
- Instructors: other instructors' drafts, learners' email addresses, admin categories editing.
- Admin: nothing hidden for moderation, but never a learner's password or payment details.

## Options

- Discussion inline under the lesson (default) or in a "Q&A" tab beside the player.
- Curriculum beside the player (desktop default) or in a drawer.
- Paid courses (price, checkout through the payments plugin) or free with enrollment only.
- Auto-complete a video lesson at its end, or only with Mark complete.
- Certificates: a "Certificate" button on the completed course when progress is 100% and quizzes pass.
- Reviews open to enrolled learners only (default) or only after completion.

## Slots used

- `action-bar`
- `author-card`
- `card-grid`
- `card-list`
- `card-row`
- `comment-thread`
- `cta-panel`
- `curriculum`
- `data-table`
- `filter-bar`
- `form`
- `highlights`
- `kpi-row`
- `lesson-player`
- `media`
- `media-upload`
- `profile-header`
- `progress-bar`
- `quiz`
- `record-header`
- `resume-card`
- `review-list`
- `search-bar`
- `status-pill`
- `tab-strip`
- `workflow-bar`
