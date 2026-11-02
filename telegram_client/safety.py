from telethon import types, utils


class SafetyError(Exception):
    pass


def is_group(entity):
    if isinstance(entity, types.Chat):
        return not (entity.deactivated or entity.left or entity.migrated_to)
    return (isinstance(entity, types.Channel) and bool(entity.megagroup) and
            not entity.broadcast and not entity.left)


def validate_group(entity, expected_id):
    if not is_group(entity) or utils.get_peer_id(entity) != expected_id:
        raise SafetyError("Группа недоступна или её идентификатор изменился. Повторите сканирование.")
    return entity


def own_message(message, owner_id, group_id, dates):
    # Never trust .out, a search filter, a forwarded author, or a cached scan alone.
    if not isinstance(message, types.Message) or message.action is not None:
        return False
    if not isinstance(message.from_id, types.PeerUser):
        return False
    if message.sender_id != owner_id or message.from_id.user_id != owner_id:
        return False
    if not isinstance(message.peer_id, (types.PeerChat, types.PeerChannel)):
        return False
    return (utils.get_peer_id(message.peer_id) == group_id and
            type(message.id) is int and message.id > 0 and dates.contains(message.date))
