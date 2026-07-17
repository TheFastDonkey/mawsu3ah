# PRD — Open Arabic Encyclopedia for Book Editions

## Summary

An open, community-driven Arabic encyclopedia for physical Arabic books. Each book (title + required author) can belong to multiple categories and can have multiple editions submitted by users. An edition carries publisher, optional year, and optional editor. Submissions enter an admin approval queue before going live. Approved editions are ranked by likes from authenticated users only; expert contributors are visually highlighted. Users can leave likeable reviews on each edition and reply to those reviews (threaded comments). The interface is Arabic-only, RTL, modern Islamic aesthetic, light enough for weak devices, with dark mode.

## Goals

- Build a trusted catalog of the best physical editions for Arabic books.
- Let the community contribute editions and vote on accuracy via likes.
- Keep moderation auditable and simple for admins.

## Non-Goals

- Digital books, audiobooks, manuscripts.
- Multi-language UI.
- Social networking beyond comments and likes.
- Recommendation engine.

## Users & Roles

- **Visitor**: search and view approved content.
- **Contributor**: authenticated user who submits editions, reviews, replies, and likes.
- **Expert**: contributor with an expert flair assigned by an admin. Their editions, reviews, and replies are visually distinct.
- **Admin**: reviews the approval queue, manages categories, users/flairs, hides reviews/replies, rejects or approves editions.

## Core Features

### Categories

- Flat list managed by admins.
- Each book can belong to multiple categories.
- Category pages list all books associated with that category.
- Users may suggest new categories globally; new-category requests still enter an admin moderation queue.
- Users may suggest adding an existing category to a book; the suggestion appears immediately on the book page as an unverified/dim chip.
- Authenticated users can like or dislike an unverified category suggestion.
- A suggestion with a net score of +3 becomes verified and is promoted to a regular book category.
- A suggestion with a net score of -3 is rejected and disappears from the public book page, but remains visible in the suggester’s contributions.
- Admins retain the ability to instantly approve or reject any suggestion.

### Books

- Identity: title (Arabic) + required author.
- Belongs to one or more categories.
- Optional aliases and disambiguation note for duplicate titles.
- Slug for URLs.

### Editions

- Belongs to one book.
- Fields: publisher (required), year (optional), editor (optional), page count (optional), city (optional), ISBN (optional), cover image (optional).
- Status: pending, approved, rejected.
- Only approved editions are visible to visitors.
- Submitter name and date shown on approved editions.

### Submission & Moderation

- Authenticated users submit editions.
- Submissions go to a pending queue.
- Admins approve or reject with a reason; submitters are notified of rejection.
- Duplicate detection suggestion before submission.

### Likes

- One like per user per edition.
- Unlike allowed.
- Only authenticated users can like.
- Approved editions default sort: most liked first.

### Reviews & Replies

- Reviews are long-form written comments on each edition (no star rating).
- Replies can be threaded under any review.
- Reviews and replies are likeable (one per user per review).
- Admins can hide or delete reviews/replies.
- Reviews are sorted by expert status first, then by like count, then by newest first.

### Expert Visibility

- Expert badge shown on user submissions, reviews, and replies.
- Optional filter to show expert editions first while preserving like count sort as secondary.

### Search

- Search books by title, author, publisher, editor, category.
- Filter by category.
- Arabic-friendly prefix/full-text search.

### Design

- Arabic-only RTL interface.
- Modern Islamic aesthetic: clean typography, geometric accents, restrained palette.
- Minimal JS; HTMX for likes, reviews, replies, and submissions.
- Dark mode toggle.
- Lightweight pages for weak devices and slow networks.

## Tech Stack

- **Backend**: Django 5.x (Python). Chosen for built-in admin, auth, ORM, migrations, and security defaults, which shortens the admin-heavy workflow.
- **Frontend**: Django templates + HTMX + vanilla CSS.
- **Database**: PostgreSQL in production; SQLite acceptable for local development.
- **Search**: PostgreSQL full-text search initially; Elasticsearch only if scale demands it.
- **Auth**: Email/password registration plus magic-link login. Admin accounts require 2FA.
- **Deployment**: Any VPS or Python PaaS.

## Data Model

- **User** (extends Django AbstractUser): email verified flag, reputation score, is_expert flag, flairs.
- **Category**: name, slug.
- **Book**: title, author, categories M2M (through `BookCategory` with ordering), aliases, disambiguation, created_at.
- **Edition**: book FK, publisher, year, editor, page_count, city, isbn, cover_image, status, submitted_by FK, submitted_at, approved_by FK, approved_at, rejection_reason.
- **Like**: user FK, edition FK, created_at. Unique together (user, edition).
- **Review**: edition FK, user FK, parent FK (self, nullable), body, hidden flag, created_at.
- **ReviewLike**: user FK, review FK. Unique together (user, review).
- **ApprovalLog**: edition FK, admin FK, old_status, new_status, reason, timestamp.

## Key Views / Endpoints

- Home / book search
- Category page with book list
- Book detail with edition list
- Edition submit form
- Edition like/unlike (HTMX)
- Review list/add/reply/like (HTMX)
- Admin approval queue
- User profile

## Security

- No local storage of plaintext credentials beyond Django defaults.
- CSRF enforcement on all state-changing requests.
- Rate limiting on login, registration, submission, like, review, and reply endpoints.
- Magic links expire quickly and are single-use.
- Admin 2FA mandatory.
- XSS mitigation via Django template escaping; no raw HTML from users.
- SQL injection protected by ORM.

## MVP Scope

- Email/password and magic-link auth.
- Category management by admins.
- Book and edition submission.
- Admin approval queue with reason logging.
- Search and edition sort by likes.
- Reviews with threaded replies and likes.
- Expert flair assigned by admins.
- Optional edition cover image upload.
- RTL UI with dark mode.

## Out of MVP

- Bulk import from external catalogs.
- Admins ability to edit flair names, without changing user's permissions.
