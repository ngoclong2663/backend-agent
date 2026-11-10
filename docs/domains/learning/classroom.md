# Learning: classroom (cohorts with due dates)

A class runs for a cohort over set dates. A teacher posts lessons and assignments with due dates, learners work
through them in order, submit work and get grades. Compared with the course catalogue, time matters: what is due
next drives the home page.

## Studied

- Google Classroom: class stream, classwork by topic, assignments with due dates and grading.
- Canvas LMS: course modules, assignments, quizzes, gradebook, a to-do list.
- Moodle: course sections with activities, completion tracking, quizzes and forums.
- Microsoft Teams for Education (Assignments): class teams with assignments and a grades tab.
- Schoology: courses with materials, an upcoming list and a gradebook.
- Brightspace (D2L): content modules, progress, discussions and due dates.
- Seesaw: younger learners' class activities with teacher review.

## People and areas

| Role | Area | First device |
|---|---|---|
| Learner | Learners (my classes, to-do, work) | Mobile-first, works on desktop |
| Teacher | Teaching (classes, classwork, grading) | Desktop |
| Admin | Admin (classes, enrolments, people) | Desktop |

## Pages

### Learners

| Page | Reached by | Sections in order | Actions |
|---|---|---|---|
| Home | Menu tab "Home" | `resume-card`: up next (class, lesson or assignment title, due date, `status-pill`) · `due-list`: due this week across classes (title, class, due date, `status-pill`: to do, submitted, late, graded) · `card-grid`: my classes (title, teacher, `progress-bar`, next due date) | Resume, open an item, open a class |
| Class | Card in My classes | `record-header`: class title, teacher, dates · `tab-strip`: Stream, Classwork, Grades · Stream: `card-list` of announcements (author, text, time) with `comment-preview` · Classwork: `curriculum` by module (lessons, assignments, quizzes in order, done ticks, due dates, `status-pill`) · Grades: `data-table` (item, due, score, feedback) · `progress-bar`: share of items done | Switch tab, open an item, comment on an announcement |
| Lesson | Classwork row, Resume | `lesson-player`: video or written body, attachments · `action-bar`: Mark done (toggle with state), Next · `comment-thread`: class questions on this lesson (author, text, replies, teacher answer marked) | Mark done, next, ask, reply |
| Assignment | Classwork row, a `due-list` row | `record-header`: title, due date, points, `status-pill` · `article-reader`: instructions, attachments · `submission-box`: my files or text, Turn in, Unsubmit before the due date, the grade and feedback once returned · `comment-thread`: private comments with the teacher | Attach, turn in, unsubmit, comment |
| Quiz | Classwork row, end of a lesson | `record-header`: title, due date, time limit, attempts left · `quiz`: questions, Submit, score and answers when the teacher releases them | Start, submit |
| To-do | Menu tab "To-do" | `tab-strip`: Upcoming, Past due, Done · `due-list`: items across classes by due date | Open an item |
| Grades | Menu tab "Grades" | `card-list`: per class (title, current grade, `progress-bar`) · `data-table`: the selected class's items (score, feedback) | Open a class's grades |

### Teaching

| Page | Reached by | Sections in order | Actions |
|---|---|---|---|
| My classes | Menu "Classes" (home) | `card-grid`: classes (title, learner count, to grade count) | New class, open a class |
| Class | Card | `tab-strip`: Stream, Classwork, People, Grades · Stream: `form` to post an announcement, `card-list` of posts · Classwork: `curriculum` editable by module · People: `data-table` (learners, invite code) · Grades: `data-table` gradebook (learners by items, scores, late flags) | Post, add item, reorder, invite, open gradebook |
| Item editor | "Create" in Classwork | `form`: kind (lesson, assignment, quiz), title, body, attachments (`media-upload`), points, due date, module · `quiz`: questions and answers when the kind is quiz · `workflow-bar`: draft, scheduled, published | Save, schedule, publish |
| Grading | "To grade" on a class or item | `filter-bar`: turned in, missing, graded · `review-queue`: submissions (learner, turned in time, late flag) · `submission-box`: the selected work · `form`: score, feedback | Grade, return, next submission |

### Admin

| Page | Reached by | Sections in order | Actions |
|---|---|---|---|
| Classes | Menu "Classes" | `filter-bar`: term, teacher · `data-table`: classes (title, teacher, learner count, dates) | Create, archive |
| People | Menu "People" | `data-table`: users (name, role, classes) | Invite, change role, enrol in a class |

## Main tasks

| Task | Role | Path (click by click) | Clicks | Budget |
|---|---|---|---|---|
| resume-lesson: resume the last lesson from home | Learner | Home: Resume on the `resume-card` | 1 | 1 |
| see-progress: see progress per class | Learner | Home: each class card shows its progress bar | 0 | 1 |
| complete-lesson: mark a lesson complete | Learner | Home: Resume (1), Mark done (2) | 2 | 2 |
| answer-question: reply to a question under a lesson | Learner | Home: Resume (1), Reply on a question (2), type, Post (3) | 3 | 3 |
| submit-quiz: submit a quiz | Learner | Home: a quiz row in the `due-list` (1), Start (2), choose answers, Submit (3) | 3 | 4 |
| Turn in an assignment | Learner | Home: the assignment in the `due-list` (1), Add file (2), pick the file (3), Turn in (4) | 4 | 4 |
| See what is due this week | Learner | Home: the `due-list` | 0 | 1 |
| Grade a submission | Teacher | My classes: "To grade" on a class (1), a submission (2), type score and feedback, Return (3) | 3 | 3 |
| Post an assignment with a due date | Teacher | A class (1), Classwork tab (2), Create (3), fill fields, Publish (4) | 4 | 4 |

## Data the pages need

- Class card: `title`, `teacherName`, `progress`*, `nextDue`*, `toGradeCount`* (teacher).
- Item (lesson, assignment, quiz): `title`, `kind`, `module`, `position`, `dueAt`, `points`, `publishedAt`,
  `statusForMe`* (to do, done, submitted, late, missing, graded), `doneByMe`*.
- Resume card: `upNext`* (the first item not done, ordered by due date then position), `lastLesson`*.
- Submission: `files`, `text`, `turnedInAt`, `late`*, `score`, `feedback`, `returnedAt`.
- Quiz: `questions`, `choices`, `timeLimit`, `attemptsLeft`*, `score`*, `answersReleased`.
- Grades: `currentGrade`* per class, `score` and `feedback` per item.
- Questions: `author`, `text`, `replies`, `isTeacher`* on each reply.

\* computed by the server. Late and missing come from `dueAt` and `turnedInAt`; the client never decides them.

## States

- No classes yet: a "Join a class" field for the class code, nothing else.
- Nothing due: the `due-list` says the week is clear and shows the next due date, if any.
- Past due: the item stays turn-in-able unless the teacher closed it, marked late.
- Unsubmit before the due date reopens the work; after grading it is locked.
- Grade not yet returned: the score field shows "not graded" to the learner, never a draft score.
- Upload error on turn in: keep the attached files listed with a retry, never lose the text.

## Never shown to

- Learners: other learners' submissions, scores and private comments, draft or scheduled items, the gradebook,
  quiz answers before release.
- Teachers: classes they do not teach, learners' passwords.
- Admin: grade edits happen in the teacher's area, not here.

## Options

- Questions under each lesson (default) or one class Stream for all discussion.
- Self-paced inside the class (all items open) or released by date.
- Grades as points, percentages or pass and fail.
- Late work accepted with a flag (default) or closed at the due date.
- A class code to join (default) or enrolment by the admin only.

## Slots used

- `action-bar`
- `article-reader`
- `card-grid`
- `card-list`
- `comment-preview`
- `comment-thread`
- `curriculum`
- `data-table`
- `due-list`
- `filter-bar`
- `form`
- `lesson-player`
- `media-upload`
- `progress-bar`
- `quiz`
- `record-header`
- `resume-card`
- `review-queue`
- `status-pill`
- `submission-box`
- `tab-strip`
- `workflow-bar`
