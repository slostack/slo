---
name: build-event-handlers
description: Event handlers (NATS or other event systems) — handler.py routing, base.py
  imports.
when_to_use: Use when wiring a new event subscriber or publisher.
group: coding
kind: skill
source_prompt: build-event-handlers.md
---

# Build Event Handlers

## Skill summary

- **Name:** `build-event-handlers`
- **Description:** Event handlers (NATS or other event systems) — handler.py routing, base.py imports.
- **When to use:** Use when wiring a new event subscriber or publisher.
- **Group:** `coding`
- **Kind:** `skill`
- **Source prompt:** `build-event-handlers.md`

## Examples

- The user asks: "Add or revise the event handlers for this feature."
- You want the canonical build pattern before touching event handlers.

## Guidance

## Event Handlers

Event handlers are services that act on listening to an event. For example here is the file defined under a folder `src/event_handlers`

1. We define the primary `handler.py` file which takes care of all the necessary routing of events to the handlers. 

> **Note**
This example uses synchronous database connections but you may need to use async ones. 

```python
from sqlalchemy.orm.session import Session
from bushido.domains.system_event.dao import SystemEventDAO
from bushido.event_handlers.base import handlers
from config import log_info

class EventHandler:
    @staticmethod
    async def process(event_dao: SystemEventDAO, db_session: Session):
        log_info(msg=f'Event: {event_dao.event_name} arrived')
        
        for event_handler in handlers:
            await event_handler.process(event_dao=event_dao, db_session=db_session)
        return 
```

The `base.py` file imports all the available handlers

```python
from bushido.event_handlers.clever_tap_coach_profile_event_handler import CleverTapCoachProfileEventHandler
from bushido.event_handlers.clever_tap_guest_user_order_create_event_handler import (
    CleverTapGuestUserOrderCreateEventHandler,
)
from bushido.event_handlers.daily_activity_level_logged_event_handler import (
    DailyActivityLevelLoggedEventHandler,
)
from bushido.event_handlers.exercise_level_logged_event_handler import (
    ExerciseLevelLoggedEventHandler,
)
from bushido.event_handlers.personal_attributes_updated_event_handler import (
    PersonalAttributesUpdatedEventHandler,
)
from bushido.event_handlers.target_weight_reached_event_handler import (
    TargetWeightReachedEventEventHandler,
)
from bushido.event_handlers.user_goal_reached_event_handler import (
    UserGoalReachedEventEventHandler,
)
from bushido.event_handlers.weight_logged_event_handler import WeightLoggedEventHandler
from bushido.event_handlers.food_logged_event_handler import FoodLoggedEventHandler
from bushido.event_handlers.food_log_deleted_event_handler import (
    FoodLogDeletedEventHandler,
)
from bushido.event_handlers.insights_generator_event_handler import (
    InsightsGeneratorEventHandler,
)
from bushido.event_handlers.finished_day_confirmation_event_handler import (
    FinishedDayConfirmationEventHandler,
)
from bushido.event_handlers.user_profile_loaded_event_handler import (
    UserProfileLoadedEventHandler,
)
from bushido.event_handlers.leaderboard_event_handler import LeaderboardEventHandler
from bushido.event_handlers.access_code_activated_event_handler import (
    AccessCodeActivatedEventHandler,
)
from bushido.event_handlers.email_live_session_participant_event_handler import (
    EmailLiveSessionParticipantEventHandler,
)
from bushido.event_handlers.email_live_session_host_event_handler import (
    EmailLiveSessionHostEventHandler,
)

handlers = [
    InsightsGeneratorEventHandler,
    DailyActivityLevelLoggedEventHandler,
    PersonalAttributesUpdatedEventHandler,
    WeightLoggedEventHandler,
    ExerciseLevelLoggedEventHandler,
    TargetWeightReachedEventEventHandler,
    UserGoalReachedEventEventHandler,
    FoodLoggedEventHandler,
    FoodLogDeletedEventHandler,
    FinishedDayConfirmationEventHandler,
    UserProfileLoadedEventHandler,
    LeaderboardEventHandler,
    AccessCodeActivatedEventHandler,
    EmailLiveSessionParticipantEventHandler,
    EmailLiveSessionHostEventHandler,
    CleverTapGuestUserOrderCreateEventHandler,
    CleverTapCoachProfileEventHandler,
]
```

A handler looks like this 

```python
from typing import Dict, Any
from sqlalchemy.orm.session import Session
from bushido.domains.system_event.dao import SystemEventDAO
from config import log_error, log_info
from bushido.domains.mailers.service import MailerService


class EmailLiveSessionHostEventHandler:
    @staticmethod
    async def process(event_dao: SystemEventDAO, db_session: Session):
        if not (event_dao.event_name == "EmailLiveSessionHostEvent"):
            return

        log_info(
            msg=f"EmailLiveSessionHostEvent called with {event_dao.event_name}"
        )
        live_session_host: Dict[str, Any] = event_dao.payload.get(
            "email_live_session_host", {}
        )
        if not live_session_host:
            log_info(msg=f"No email sent for event_name: {event_dao.event_name}")
            return

        try:
            await MailerService.send_live_session_host_info_mail(
                email_live_session_host_dao=live_session_host
            )
        except Exception as e:
            log_error(
                msg=f"Error sending email for live session host: {e}",
                loc=f"{__name__}",
                method="process",
                e=e,
            )
        return
```
Here the handler identifies if it should process the event and passes it on to the application service responsible for processing it. 

The handlers never throw an exception and ensure that the handler chain is never broken. 

Here is another example


```python
from typing import Dict, List
from sqlalchemy.orm.session import Session
from bushido.domains.system_event.dao import SystemEventDAO
from config import log_debug, log_info
from bushido.domains.user.dao import UserDAO
from bushido.domains.step_count_log.dao import StepCountLogDAO
from bushido.domains.scores.dao import ScoreDAO
from bushido.services.v2.leaderboards.update.service import (
    LeaderboardUpdateOnStepCountLogAppService,
    LeaderboardUpdateOnScoreComputedAppService,
)
from bushido.domains.step_count_log.event import StepCountLoggedEventDAO
from uuid import UUID


async def trigger_leaderboad_update_on_step_count_logged_event(
    user_id: UUID, event_dao: SystemEventDAO, db_session: Session
):
    event_payload: Dict = event_dao.payload
    user_dao: UserDAO = UserDAO(**event_payload.get("user_dao", {}))
    step_count_logs: List[Dict] = event_payload.get("step_count_log_dao", [])
    step_count_log_daos: StepCountLogDAO = [
        StepCountLogDAO(**step_count_log) for step_count_log in step_count_logs
    ]
    svc = LeaderboardUpdateOnStepCountLogAppService(
        user=user_dao,
        step_count_logs=step_count_log_daos,
        db_session=db_session,
    )
    await svc()
    return

async def trigger_leaderboard_update_on_score_computed_event(
    user_id: UUID, event_dao: SystemEventDAO, db_session: Session,
):
    event_payload: Dict = event_dao.payload
    user_dao: UserDAO = UserDAO(**event_payload.get("user", {}))
    score_dao: ScoreDAO = ScoreDAO(**event_payload.get("score", {}))
    svc = LeaderboardUpdateOnScoreComputedAppService(user=user_dao, score_dao=score_dao, db_session=db_session)
    await svc()
    return 
    

class LeaderboardEventHandler:
    @staticmethod
    async def process(event_dao: SystemEventDAO, db_session: Session = None):
        if not (
            (event_dao.event_name == "ScoreComputedEvent")
            or (event_dao.event_name == "StepCountLoggedEvent")
        ):
            return

        log_info(msg=f"LeaderboardEventHandler called with {event_dao.event_name}")

        user_id = event_dao.payload.get("user", {}).get("id", None)

        if event_dao.event_name == "StepCountLoggedEvent":
            await trigger_leaderboad_update_on_step_count_logged_event(
                user_id=user_id,
                event_dao=event_dao,
                db_session=db_session,
            )
        elif event_dao.event_name == "ScoreComputedEvent":
            await trigger_leaderboard_update_on_score_computed_event(
                user_id=user_id,
                event_dao=event_dao,
                db_session=db_session,
                
            )
```

When it comes to testing the events

1. In the application service we care if an event was triggered with the right arguments. 
2. We test the application service that the event handler invokes.
