_BT_PYTHON_V_EVN_PATH="/www/server/pyporject_evn"

ACTIVATE_NAME="${1}"
if [ -z "${ACTIVATE_NAME}" ]; then
  echo "使用：\" source btpyprojectenv <project_name> \"启动虚拟环境"
  echo "使用：\" deactivate \"命令, 退出虚拟环境, 回到之前的环境"
  echo "（仅支持Linux服务器使用）"
  return 1
fi

if [ ! -d "${_BT_PYTHON_V_EVN_PATH}/${ACTIVATE_NAME}_venv" ]; then
  echo "项目名称为：${ACTIVATE_NAME} 的虚拟环境不存在"
  return 1
fi

# This file must be used with "source bin/activate" *from bash*
# You cannot run it directly

deactivate () {
    # reset old environment variables
    if [ -n "${_OLD_VIRTUAL_PATH:-}" ] ; then
        PATH="${_OLD_VIRTUAL_PATH:-}"
        export PATH
        unset _OLD_VIRTUAL_PATH
    fi
    if [ -n "${_OLD_VIRTUAL_PYTHONHOME:-}" ] ; then
        PYTHONHOME="${_OLD_VIRTUAL_PYTHONHOME:-}"
        export PYTHONHOME
        unset _OLD_VIRTUAL_PYTHONHOME
    fi

    # This should detect bash and zsh, which have a hash command that must
    # be called to get it to forget past commands.  Without forgetting
    # past commands the $PATH changes we made may not be respected
    if [ -n "${BASH:-}" ] || [ -n "${ZSH_VERSION:-}" ] ; then
        hash -r 2> /dev/null
    fi

    if [ -n "${_OLD_VIRTUAL_PS1:-}" ] ; then
        PS1="${_OLD_VIRTUAL_PS1:-}"
        export PS1
        unset _OLD_VIRTUAL_PS1
    fi

    unset VIRTUAL_ENV
    unset VIRTUAL_ENV_PROMPT
    if [ ! "${1:-}" = "nondestructive" ] ; then
    # Self destruct!
        unset -f deactivate
    fi
}

# unset irrelevant variables
deactivate nondestructive

# use the path as-is
export VIRTUAL_ENV="${_BT_PYTHON_V_EVN_PATH}/${ACTIVATE_NAME}_venv"


_OLD_VIRTUAL_PATH="$PATH"
PATH="$VIRTUAL_ENV/bin:$PATH"
export PATH

# unset PYTHONHOME if set
# this will fail if PYTHONHOME is set to the empty string (which is bad anyway)
# could use `if (set -u; : $PYTHONHOME) ;` in bash
if [ -n "${PYTHONHOME:-}" ] ; then
    _OLD_VIRTUAL_PYTHONHOME="${PYTHONHOME:-}"
    unset PYTHONHOME
fi

if [ -z "${VIRTUAL_ENV_DISABLE_PROMPT:-}" ] ; then
    _OLD_VIRTUAL_PS1="${PS1:-}"
    PS1="(${ACTIVATE_NAME}) ${PS1:-}"
    export PS1
    VIRTUAL_ENV_PROMPT="(${ACTIVATE_NAME}) "
    export VIRTUAL_ENV_PROMPT
fi

# This should detect bash and zsh, which have a hash command that must
# be called to get it to forget past commands.  Without forgetting
# past commands the $PATH changes we made may not be respected
if [ -n "${BASH:-}" ] || [ -n "${ZSH_VERSION:-}" ] ; then
    hash -r 2> /dev/null
fi
