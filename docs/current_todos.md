# Current Todos

Current Goal: Implement Advent Calender functionality with image storage and retrieval functionality.

User Story: As a user, I want to be able to create, retrieve, and delete advent calendar entries that reference included images stored in S3, so that I can manage my advent calendar effectively.

User Story: As a user, I want to be able to upload, retrieve, and delete images stored in S3, so that I can manage my images effectively.

User Story: As a user, I want to be able to only receive advent calender entries if I provide valid authentication in the form of a password (tech: encrypteded version of pwd in x-api-key header, and checked in our auth middleware), so that my advent calendar entries are secure.

- [ ] Add Advent Model
- [ ] Add Image Reference Model

- [ ] Add advent routes
    - [ ] POST /advent
    - [ ] GET /advent/today
    - [ ] GET /advent/:day
    - [ ] DELETE /advent/:day

- [ ] Add Image routes
    - [x] POST /image
    - [x] GET /image/:id
    - [ ] DELETE /image/:id

- [ ] Add Login route

- [ ] Add AdventService

- [x] Add image repository
- [ ] Add advent repository

- [x] Add s3 db adapter

- [ ] Add auth middleware (api-key)
- [ ] Add Session Manager / Auth Service

- [ ] health check endpoint for DB and S3

- [ ] Add tests for advent routes
