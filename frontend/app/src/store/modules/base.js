import rest from '../../api/rest'
import * as types from '../mutation-types'

// Contains basic store
const state = {
  token: false,
  user: '',
  isSuperuser: false,
  channel: '',
  loading: [],
  errors: [],
  loginSuccess: false,
  loginMessage: '',
  userMessages: [],
  conWorker: null,
  conRemote: null
}

const getters = {
  loginSuccess: state => state.loginSuccess,
  loginMessage: state => state.loginMessage,
  loading: state => state.loading.length > 0,
  error: state => state.errors.length > 0,
  errors: state => state.errors,
  token: state => state.token,
  user: state => state.user,
  isSuperuser: state => state.isSuperuser,
  channel: state => state.channel,
  userMessages: state => state.userMessages,
  conWorker: state => state.conWorker,
  conRemote: state => state.conRemote
}

const actions = {
  login ({commit}, dat) {
    rest.login(dat)
      .then(response => {
        // console.log(response)
        const token = response.data[0].key
        const username = dat.user
        const isSuperuser = response.data[0].is_superuser
        const channel = response.data[0].channel
        commit(types.LOGIN, { token, username, isSuperuser, channel })

        rest.setToken(token)
      })
      .catch(error => {
        // commit(types.PUSH_ERROR, { error })
        commit(types.LOGIN_ERROR, { error })
      })
  },
  testConnectionWorker ({commit}, dat) {
    commit(types.PUSH_LOADING)
    rest.testConnectionWorkerJob(dat)
      .then(response => {
        commit(types.POP_LOADING)
      })
      .catch(error => {
        commit(types.POP_LOADING)
        commit(types.PUSH_ERROR, { error })
      })
  },
  testConnectionServershark ({commit}, dat) {
    commit(types.PUSH_LOADING)
    rest.testConnectionServersharkJob(dat)
      .then(response => {
        commit(types.POP_LOADING)
      })
      .catch(error => {
        commit(types.POP_LOADING)
        commit(types.PUSH_ERROR, { error })
      })
  },
  pushUserMessage ({commit}, message) {
    commit(types.PUSH_USER_MESSAGE, { message })
  },
  popUserMessage ({commit}, message) {
    commit(types.POP_USER_MESSAGE, { message })
  },
  logout ({commit}) {
    commit(types.LOGOUT)
  },
  pushLoading ({commit}) {
    commit(types.PUSH_LOADING)
  },
  popLoading ({commit}) {
    commit(types.POP_LOADING)
  },
  pushError ({commit}, error) {
    commit(types.PUSH_ERROR, { error })
  },
  popError ({commit}, id) {
    commit(types.POP_ERROR, { id })
  }
}

const mutations = {
  [types.LOGIN] (state, { token, username, isSuperuser, channel }) {
    state.token = token
    state.user = username
    state.isSuperuser = isSuperuser
    state.channel = channel
    state.loginSuccess = true
    state.loginMessage = ''
    rest.setToken(token)
  },
  [types.LOGOUT] (state) {
    state.loginSuccess = false
    state.loginMessage = ''
    state.token = null
    state.channel = ''
    state.isSuperuser = false
  },
  [types.PUSH_LOADING] (state) {
    state.loading.push(true)
  },
  [types.POP_LOADING] (state) {
    state.loading.pop()
  },
  [types.LOGIN_ERROR] (state, { error }) {
    state.loginMessage = 'Login failed'
  },
  [types.PUSH_ERROR] (state, { error }) {
    // console.log('api error', error)
    let message = ''
    if (typeof error.response !== 'undefined') {
      message = error.response.statusText
    } else {
      message = error.message
    }
    const dat = {'message': message,
      'id': state.errors.length,
      'full_error': error}
    state.errors.push(dat)
  },
  [types.POP_ERROR] (state, { id }) {
    state.errors.splice(id, 1)
  },
  [types.PUSH_USER_MESSAGE] (state, { message }) {
    // todo: is there abetter way to do this?
    if (message.created === false && message.job_type === 'test_connection_servershark') {
      state.conRemote = message.success
    }
    if (message.created === false && message.job_type === 'test_connection_worker') {
      state.conWorker = message.success
    }
    state.userMessages.push(message)
  },
  [types.SET_USER_MESSAGES] (state, { messages }) {
    state.userMessages = messages
  },
  [types.POP_USER_MESSAGE] (state, { message }) {
    state.userMessages = state.userMessages.filter(item => item !== message)
  }
}

export default {
  state,
  getters,
  actions,
  mutations
}
