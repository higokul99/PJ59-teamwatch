# Product Requirement Document (PRD)

| Metadata | Details |
| :--- | :--- |
| **Project / Portal** | Admin Portal (e.g., `teamwatch/admin-portal`) |
| **Document Version** | `v1.0.0` |
| **Status** | `Draft` / `In Review` / `Approved` |
| **Author / Owner** | Gokul |
| **Target Release** | Sprint 1 / Nov 12, 2026 10PM |

## 1. Executive Summary & Problem Statement
### 1.1. Background & Context

Admin Portal is a comprehensive web application designed to provide centralized management and administration capabilities for the **TeamWatch** ecosystem. It serves as the single source of truth for system configuration, user management, and overall operational oversight.

This document outlines the vision, features, and technical direction for the Admin Portal, ensuring alignment across development, design, and product stakeholders.

### 1.2. Problem Statement

Currently, the administration of TeamWatch requires manual intervention and access to multiple systems, making it inefficient and prone to errors. The lack of a centralized administration interface creates several challenges:

- **Lack of Centralized Management**: Admins need to access multiple systems to manage users, roles, permissions, and system configurations.
- **Inefficient User Management**: Creating, updating, or deleting user accounts across different systems is a time-consuming process.
- **Limited Visibility**: Admins lack a comprehensive view of system operations, user activities, and overall system health.
- **Configuration Drift**: Manual configuration across different systems can lead to inconsistencies and configuration drift.
- **Scalability Issues**: As the user base grows, manual administration becomes increasingly difficult to manage.

### 1.3. Solution Overview

The Admin Portal will provide a centralized, web-based interface for comprehensive administration of the TeamWatch ecosystem. It will empower administrators to efficiently manage all aspects of the system, including users, roles, permissions, system configurations, and operational monitoring. The portal will serve as the single source of truth for all administrative activities, ensuring consistency, visibility, and control over the entire system.

## 2. Goals & Objectives
### 2.1. Business Goals

- **Improve Operational Efficiency**: Reduce manual administrative tasks and streamline workflows.
- **Enhance System Control**: Provide administrators with comprehensive control over all system operations.
- **Ensure Scalability**: Enable efficient management of a growing user base and system complexity.
- **Improve Visibility**: Provide real-time insights into system operations and user activities.
- **Maintain Compliance**: Ensure consistent application of policies and configurations across the ecosystem.

### 2.2. User Goals

- **Efficient User Management**: Easily create, update, and manage user accounts with minimal effort.
- **Role-Based Access Control**: Define and manage roles and permissions to ensure appropriate access levels.
- **System Configuration**: Configure and manage system settings according to organizational requirements.
- **Operational Monitoring**: Monitor system health, user activities, and overall system performance.
- **Audit Trail**: Maintain a comprehensive audit trail of all administrative activities for compliance and troubleshooting.

### 2.3. Project Goals

- **Deliver a High-Quality Product**: Develop a robust, scalable, and maintainable Admin Portal application.
- **Ensure Security**: Implement appropriate security measures to protect sensitive administrative data.
- **Provide Excellent User Experience**: Design an intuitive and user-friendly interface for administrators.
- **Ensure Performance**: Deliver a fast and responsive application that can handle concurrent administrative operations.
- **Enable Future Extensibility**: Design the architecture to support future enhancements and integrations.

### 2.4 Developer Point of view goal
- **Learning opportunity**: Provide a platform for developers to learn and grow their skills in web development, cloud computing, and project management.
- **Career growth**: Enable developers to build a portfolio of projects that can help them advance their careers.
- **Team collaboration**: Foster a culture of collaboration and teamwork among developers.
- **Innovation**: Encourage innovation and creativity in problem-solving.
- **Impact**: Create a product that can make a positive impact on the lives of users.
- **More Details**: Using a dedicated API Routing for admin portal that is separate from the main API Routing. And this folders code will only hold FastAPI Backend only code. All CRUD will be accessed via REST API call from Frontend (Vanilla SPA).

## 3. Target Audience & User Personas

| Persona | Role / Description | Primary Needs / Pain Points |
| :--- | :--- | :--- |
| **Room Host** | Manages the movie night and system settings. | Needs visibility over connected devices and ability to resolve lag/drift. |
| **Viewer / Participant**| Joins on phone or laptop. | Needs play/pause feature also like the Room Host and ability to resolve lag/drift. |
| **System Admin** | Manages the system settings and user accounts. | Needs visibility over system health and user activities. |

## 4. User Stories
Write requirements from the perspective of the user:
*Format: As a `<role>`, I want to `<action>` so that `<business value / benefit>`.*
- **US-01**: *As an admin*, I want to see a live list of all connected devices with their drift offset, *so that* I know who is causing playback stalls.
- **US-02**: *As an admin*, I want to upload a new media file while the current movie is playing, *so that* there is zero downtime between screenings.
- **US-03**: *As an admin*, I want to force-sync all connected devices with one click, *so that* everyone is immediately re-anchored to the master timeline.
- **US-04**: *As an admin*, I want to view all the Rooms created, with CRUD action on all fields, Block Rooms, Remove the uploaded content of each rooms or all rooms(Ask confirmation with type 'CONFIRM' in text box before remove data from all rooms). 
- **US-05**: *As an admin*, I want to view all the Users created, with CRUD action on all fields, Block Users, Remove the users, Change the passcode to use for Room host , Viewer/Participant.

## 5. Functional Requirements

### 5.1. Authentication & Session Control
- **FR-1.1 [P0]**: Admin must enter a dedicated Admin Password ( 8-16 char with atleast one Upper case, one Lower case, one Number and one Special character ) to access the portal.
- **FR-1.2 [P0]**: Inactive admin sessions must automatically expire after 24 hours.
- **FR-1.3 [P1]**: Rate limit login attempts to prevent brute force (max 5 failed attempts per 10 minutes).
- **FR-1.4 [P1]**: Username of admin account to be 'hellometora@gmail.com' . This username admin user will type along with password.

## 6. Non-Functional Requirements (NFRs)
- **Performance**: Dashboard metrics must update within 500ms of any room state change.
- **Security**: No plaintext passwords; admin cookies must be HTTP-only and signed with secure HMAC.
- **Device & Browser Support**: Must work seamlessly on modern evergreen browsers (Chrome, Safari, Firefox, Edge) on both desktop and mobile screens.
- **Reliability**: If the WebSocket connection drops, the portal must automatically attempt reconnection every 3 seconds.

## 7. Edge Cases & System Behaviors
NA

## 8. Success Metrics (KPIs)
Generic success criteria only for now

## 9. User Interface (UI) / User Experience (UX) Requirements
- Will update on @ui-design.md file in same folder.

## 10. Acceptance Criteria (Definition of Done)
Checklist that QA or an AI Agent must pass before marking the feature complete:
- [ ] Admin can access the admin portal
- [ ] Admin can login with valid username and password
- [ ] Admin can logout from the admin portal
- [ ] Admin can reset password
- [ ] Admin can view all the Rooms created, with CRUD action on all fields, Block Rooms, Remove the uploaded content of each rooms or all rooms(Ask confirmation with type 'CONFIRM' in text box before remove data from all rooms). 
- [ ] Admin can view all the Users created, with CRUD action on all fields, Block Users, Remove the users, Change the passcode to use for Room host , Viewer/Participant.
- [ ] Works cleanly on mobile browser viewport (minimum 375px width).

