import enum
import datetime

from sqlalchemy import Column, Integer, Text, Enum, DateTime, ForeignKey, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from sqlalchemy.sql import func

from aiogram.types import User

from .config import DATABASE_FILE
from ..messaging import logs

engine = create_engine('sqlite:///' + DATABASE_FILE)
Session = sessionmaker(bind=engine)

Base = declarative_base()

class MonitoredLink(Base):
    __tablename__ = 'monitored_links'
    link = Column(Text, primary_key=True)
    chat_name = Column(Text)
    chat_id = Column(Integer)

class UserStatus(enum.Enum):
    NOT_AUTHORIZED = enum.auto()
    AUTHORIZING = enum.auto()
    AUTHORIZED = enum.auto()
    BANNED = enum.auto()

class BotUser(Base):
    __tablename__ = 'bot_users'
    id = Column(Integer, primary_key=True)
    username = Column(Text)
    first_name = Column(Text)
    last_name = Column(Text)
    email = Column(Text, index=True)
    code = Column(Text)
    status = Column(Enum(UserStatus))
    utm_source_id = Column(Text, ForeignKey(MonitoredLink.link))
    utm_source = relationship(MonitoredLink)
    created_at = Column(DateTime, server_default=func.now()) # pylint: disable=not-callable
    last_ad_time = Column(DateTime, default=datetime.datetime(1970, 1, 1))



if __name__ == '__main__':
    engine2 = create_engine('sqlite:///' + DATABASE_FILE, echo=True)
    Base.metadata.create_all(engine2)




def save_user(user: User, utm_source: MonitoredLink = None):
    with Session() as session:
        session.expire_on_commit = False
        bot_user = session.query(BotUser).filter(BotUser.id == user.id).first()
        if bot_user:
            if utm_source:
                bot_user.utm_source = utm_source
                logs.new_user(user, utm_source)
            session.commit()
        else:
            bot_user = BotUser(
                id=user.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name,
                status=UserStatus.NOT_AUTHORIZED,
                utm_source=utm_source
            )
            session.merge(bot_user)
            session.commit()
            logs.new_user(user, utm_source)

def save_email(user: User, email: str):
    with Session() as session:
        bot_user = session.query(BotUser).filter(BotUser.id == user.id).first()
        bot_user.email = email
        session.commit()

def get_users_with_email(email: str) -> list[BotUser]:
    email_main_part = email.split('@')[0]

    with Session() as session:
        return session.query(BotUser).filter(
            (BotUser.email.like(f'{email_main_part}@%')) & (
                (BotUser.status == UserStatus.AUTHORIZED) | (BotUser.status == UserStatus.BANNED)
            )
        ).all()

def save_code(user: User, code: str):
    with Session() as session:
        bot_user = session.query(BotUser).filter(BotUser.id == user.id).first()
        bot_user.code = code
        session.commit()
        logs.new_code(user, bot_user.email, code)

def get_user(user: User) -> BotUser | None:
    with Session() as session:
        bot_user = session.query(BotUser).filter(BotUser.id == user.id).first()
        return bot_user

def get_user_by_id(user_id: int) -> BotUser | None:
    with Session() as session:
        bot_user = session.query(BotUser).filter(BotUser.id == user_id).first()
        return bot_user

def authorize(user: User):
    with Session() as session:
        bot_user = session.query(BotUser).filter(BotUser.id == user.id).first()
        bot_user.status = UserStatus.AUTHORIZED
        session.commit()
        logs.finished_authorization(user, bot_user.utm_source)

def ban_user(user_id: int):
    with Session() as session:
        bot_user = session.query(BotUser).filter(BotUser.id == user_id).first()
        if bot_user is not None:
            bot_user.status = UserStatus.BANNED
        else:
            bot_user = BotUser(first_name='?', id=user_id, status=UserStatus.BANNED)
            session.add(bot_user)
        session.commit()
        logs.ban_user(bot_user)

def unban_user(user_id: int):
    with Session() as session:
        bot_user = session.query(BotUser).filter(BotUser.id == user_id).first()
        bot_user.status = UserStatus.AUTHORIZED
        session.commit()
        logs.unban_user(bot_user)

def update_last_ad_time(user: User):
    with Session() as session:
        bot_user = session.query(BotUser).filter(BotUser.id == user.id).first()
        bot_user.last_ad_time = datetime.datetime.now()
        session.commit()


def save_link(link: str, chat_name: str, chat_id: int):
    with Session() as session:
        session.expire_on_commit = False
        monitored_link = MonitoredLink(link=link, chat_name=chat_name, chat_id=chat_id)
        session.add(monitored_link)
        session.commit()
        logs.new_link(monitored_link)

def update_chat_id(old_link: MonitoredLink, new_chat_id: int):
    with Session() as session:
        monitored_link = session.query(MonitoredLink).filter(MonitoredLink.link == old_link.link).first()
        monitored_link.chat_id = new_chat_id
        session.commit()
        logs.chat_migrated(monitored_link, new_chat_id)

def get_link(link: str) -> MonitoredLink:
    with Session() as session:
        return session.query(MonitoredLink).filter(MonitoredLink.link == link).first()

def get_all_monitored_chats() -> list[MonitoredLink]:
    with Session() as session:
        links = session.query(MonitoredLink).all()

    chats_without_duplicates = {link.chat_id: link for link in links}
    return list(chats_without_duplicates.values())


class BroadcastDelivery(Base):
    __tablename__ = 'broadcast_deliveries'
    broadcast_id = Column(Text, primary_key=True)
    user_id = Column(Integer, primary_key=True)
    delivered_at = Column(DateTime, server_default=func.now())  # pylint: disable=not-callable


def was_broadcast_delivered(broadcast_id: str, user_id: int) -> bool:
    with Session() as session:
        return session.query(BroadcastDelivery).filter(
            BroadcastDelivery.broadcast_id == broadcast_id,
            BroadcastDelivery.user_id == user_id,
        ).first() is not None


def mark_broadcast_delivered(broadcast_id: str, user_id: int):
    with Session() as session:
        session.merge(BroadcastDelivery(broadcast_id=broadcast_id, user_id=user_id))
        session.commit()


def count_broadcast_deliveries(broadcast_id: str) -> int:
    with Session() as session:
        return session.query(BroadcastDelivery).filter(
            BroadcastDelivery.broadcast_id == broadcast_id,
        ).count()


# create new tables if missing (idempotent)
Base.metadata.create_all(engine, tables=[BroadcastDelivery.__table__])
