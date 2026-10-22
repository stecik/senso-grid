import js from '@eslint/js'
import ts from 'typescript-eslint'
import vue from 'eslint-plugin-vue'
import globals from 'globals'
export default ts.config({ignores:['dist/**','node_modules/**']},js.configs.recommended,...ts.configs.recommended,...vue.configs['flat/recommended'],{files:['**/*.vue'],languageOptions:{parserOptions:{parser:ts.parser}},rules:{'vue/multi-word-component-names':'off','vue/max-attributes-per-line':'off','vue/html-self-closing':'off','vue/singleline-html-element-content-newline':'off','vue/html-indent':'off','vue/html-closing-bracket-newline':'off','vue/attributes-order':'off','vue/first-attribute-linebreak':'off'}},{languageOptions:{globals:{...globals.browser,...globals.serviceworker,...globals.node}}})
