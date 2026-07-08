---
agent: general
doc_type: reference
category: 参考
genre: 通用
tags: []
source: []
---

# 全网最详细：DeepSeek-R1大模型嵌入Word教程，让你

全网最详细：DeepSeek-R1大模型嵌入Word教程，让你
的办公效率起飞！
效果演示

选中文本并点击生成，即可实现模型回复！例如，我们想要将一段中文文本翻译成英文。

1. 获取API key
- deepseek-r1模型API Key获取地址：https://www.deepseek.com/

- qwen2.5模型API Key获取地址：https://bailian.console.aliyun.com/

2. 配置Word
\1. 启用开发者工具

 - 新建Word，点击 文件 -> 选项 -> 自定义功能区

 - 勾选"开发者工具"

\2. 配置信任中心

 - 点击 信任中心 -> 信任中心设置

 - 选择"启用所有宏"与"信任对VBA......"

\3. 添加模块

 - 点击开发者工具，点击 Visual Basic

 - 在新窗口中点击 插入 ，选择 模块

 - 将代码复制到编辑区中（*注意替换你自己的API key***）

\4. 自定义功能区

 - 点击 文件 -> 选项 -> 自定义功能区

 - 右键开发工具，点击 添加新组

 - 右键新建组，点击 重命名

 - 将其命名为"DeepSeek"，选择心仪的图标

 - 点击确定

\5. 添加命令

 - 选择DeepSeek（自定义）

 - 在左侧命令中选择"宏"

 - 找到并选中"DeepSeekV3"，点击添加

 - 右键添加的命令，点击重命名

 - 选择开始符号作为图标

 - 重命名为"生成"
3. 使用方法
\1. 选中需要处理的文字

\2. 点击"生成"按钮

\3. 等待大模型响应

4. 创建模板
\1. 将你的文档另存为 Word 模板 (.dotm)：

 - 点击"文件" → "另存为"

 - 选择保存类型为"Word 启用宏的模板 (.dotm)"

 - 保存到 Word 的模板文件夹（通常是 C:\Users\用户名
\AppData\Roaming\Microsoft\Word\STARTUP）

 - 这样每次打开 Word 时，宏就会自动可用

相关代码

DeepSeekV3代码

 Function CallDeepSeekAPI(api_key As String, inputText As String) As String
     Dim API As String
     Dim SendTxt As String
     Dim Http As Object
     Dim status_code As Integer
     Dim response As String

     API = "https://api.deepseek.com/chat/completions"
     SendTxt = "{""model"": ""deepseek-chat"", ""messages"":
 [{""role"":""system"", ""content"":""You are a Word assistant""},
 {""role"":""user"", ""content"":""" & inputText & """}], ""stream"": false}"

     Set Http = CreateObject("MSXML2.XMLHTTP")
     With Http
         .Open "POST", API, False
         .setRequestHeader "Content-Type", "application/json"
         .setRequestHeader "Authorization", "Bearer " & api_key
         .send SendTxt
         status_code = .Status
         response = .responseText
     End With

     ' 弹出窗口显示 API 响应（调试用）

     ' MsgBox "API Response: " & response, vbInformation, "Debug Info"

     If status_code = 200 Then
         CallDeepSeekAPI = response
     Else
         CallDeepSeekAPI = "Error: " & status_code & " - " & response
     End If
   Set Http = Nothing
End Function

Sub DeepSeekV3()
   Dim api_key As String
   Dim inputText As String
   Dim response As String
   Dim regex As Object
   Dim matches As Object
   Dim originalSelection As Object

   api_key = "替换为你的api key"
   If api_key = "" Then
          MsgBox "Please enter the API key."
          Exit Sub
   ElseIf Selection.Type <> wdSelectionNormal Then
          MsgBox "Please select text."
          Exit Sub
   End If

   ' 保存原始选中的文本
   Set originalSelection = Selection.Range.Duplicate

   inputText = Replace(Replace(Replace(Replace(Replace(Selection.text, "\",
"\\"), vbCrLf, ""), vbCr, ""), vbLf, ""), Chr(34), "\""")
   response = CallDeepSeekAPI(api_key, inputText)

   If Left(response, 5) <> "Error" Then
          Set regex = CreateObject("VBScript.RegExp")
          With regex
             .Global = True
             .MultiLine = True
             .IgnoreCase = False
             .Pattern = """content"":""(.*?)"""
          End With
          Set matches = regex.Execute(response)
          If matches.Count > 0 Then
             response = matches(0).SubMatches(0)
             response = Replace(Replace(response, """", Chr(34)), """", Chr(34))

             ' 取消选中原始文本
             Selection.Collapse Direction:=wdCollapseEnd

             ' 将内容插入到选中文字的下一行
             Selection.TypeParagraph ' 插入新行
             Selection.TypeText text:=response

             ' 将光标移回原来选中文本的末尾
             originalSelection.Select
          Else
             MsgBox "Failed to parse API response.", vbExclamation
          End If
   Else
          MsgBox response, vbCritical
   End If
End Sub
deepseek-reasoner代码

 Function CallDeepSeekAPI(api_key As String, inputText As String) As String
    Dim API As String
    Dim SendTxt As String
    Dim Http As Object
    Dim status_code As Integer
    Dim response As String

    API = "https://api.deepseek.com/chat/completions"
    SendTxt = "{""model"": ""deepseek-reasoner"", ""messages"":
 [{""role"":""system"", ""content"":""You are a Word assistant""},
 {""role"":""user"", ""content"":""" & inputText & """}], ""stream"": false}"

    Set Http = CreateObject("MSXML2.XMLHTTP")
    With Http
        .Open "POST", API, False
        .setRequestHeader "Content-Type", "application/json"
        .setRequestHeader "Authorization", "Bearer " & api_key
        .send SendTxt
        status_code = .Status
        response = .responseText
    End With

    ' 弹出窗口显示 API 响应（调试用）

    ' MsgBox "API Response: " & response, vbInformation, "Debug Info"

    If status_code = 200 Then
        CallDeepSeekAPI = response
    Else
        CallDeepSeekAPI = "Error: " & status_code & " - " & response
    End If

    Set Http = Nothing
 End Function

 Sub DeepSeekV3()
    Dim api_key As String
    Dim inputText As String
    Dim response As String
    Dim regex As Object
    Dim reasoningRegex As Object
    Dim contentRegex As Object
    Dim matches As Object
    Dim reasoningMatches As Object
    Dim originalSelection As Object
    Dim reasoningContent As String
    Dim finalContent As String

    api_key = "替换为你的api key"
    If api_key = "" Then
        MsgBox "Please enter the API key."
        Exit Sub
    ElseIf Selection.Type <> wdSelectionNormal Then
        MsgBox "Please select text."
        Exit Sub
   End If

   ' 保存原始选中的文本
   Set originalSelection = Selection.Range.Duplicate

   inputText = Replace(Replace(Replace(Replace(Replace(Selection.text, "\",
"\\"), vbCrLf, ""), vbCr, ""), vbLf, ""), Chr(34), "\""")
   response = CallDeepSeekAPI(api_key, inputText)

   If Left(response, 5) <> "Error" Then
       ' 创建正则表达式对象来分别匹配推理内容和最终回答
       Set reasoningRegex = CreateObject("VBScript.RegExp")
       With reasoningRegex
            .Global = True
            .MultiLine = True
            .IgnoreCase = False
            .Pattern = """reasoning_content"":""(.*?)"""
       End With

       Set contentRegex = CreateObject("VBScript.RegExp")
       With contentRegex
            .Global = True
            .MultiLine = True
            .IgnoreCase = False
            .Pattern = """content"":""(.*?)"""
       End With

       ' 提取推理内容
       Set reasoningMatches = reasoningRegex.Execute(response)
       If reasoningMatches.Count > 0 Then
            reasoningContent = reasoningMatches(0).SubMatches(0)
            reasoningContent = Replace(reasoningContent, "\n\n", vbNewLine)
            reasoningContent = Replace(reasoningContent, "\n", vbNewLine)
            reasoningContent = Replace(Replace(reasoningContent, """", Chr(34)),
"""", Chr(34))
       End If

       ' 提取最终回答
       Set matches = contentRegex.Execute(response)
       If matches.Count > 0 Then
            finalContent = matches(0).SubMatches(0)
            finalContent = Replace(finalContent, "\n\n", vbNewLine)
            finalContent = Replace(finalContent, "\n", vbNewLine)
            finalContent = Replace(Replace(finalContent, """", Chr(34)), """",
Chr(34))

            ' 取消选中原始文本
            Selection.Collapse Direction:=wdCollapseEnd

            ' 插入推理过程（如果存在）
            If Len(reasoningContent) > 0 Then
                 Selection.TypeParagraph
                 Selection.TypeText "推理过程："
                 Selection.TypeParagraph
                 Selection.TypeText reasoningContent
                 Selection.TypeParagraph
                 Selection.TypeText "最终回答："
                 Selection.TypeParagraph
             End If

             ' 插入最终回答
             Selection.TypeText finalContent

             ' 将光标移回原来选中文本的末尾
             originalSelection.Select
          Else
             MsgBox "Failed to parse API response.", vbExclamation
          End If
   Else
          MsgBox response, vbCritical
   End If
End Sub

qwen2.5-max代码

Function CallDeepSeekAPI(api_key As String, inputText As String) As String
   Dim API As String
   Dim SendTxt As String
   Dim Http As Object
   Dim status_code As Integer
   Dim response As String

   API = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
   SendTxt = "{""model"": ""qwen-max-0125"", ""messages"":
[{""role"":""system"", ""content"":""You are a Word assistant""},
{""role"":""user"", ""content"":""" & inputText & """}]}"

   Set Http = CreateObject("MSXML2.XMLHTTP")
   With Http
          .Open "POST", API, False
          .setRequestHeader "Content-Type", "application/json"
          .setRequestHeader "Authorization", "Bearer " & api_key
          .send SendTxt
          status_code = .Status
          response = .responseText
   End With

   ' 弹出窗口显示 API 响应（调试用）
   ' MsgBox "API Response: " & response, vbInformation, "Debug Info"

   If status_code = 200 Then
          CallDeepSeekAPI = response
   Else
          CallDeepSeekAPI = "Error: " & status_code & " - " & response
   End If

   Set Http = Nothing
End Function

Sub DeepSeekV3()
   Dim api_key As String
   Dim inputText As String
   Dim response As String
   Dim regex As Object
   Dim matches As Object
     Dim originalSelection As Object

     api_key = "替换为你的api key"
     If api_key = "" Then
          MsgBox "Please enter the API key."
          Exit Sub
     ElseIf Selection.Type <> wdSelectionNormal Then
          MsgBox "Please select text."
          Exit Sub
     End If

     ' 保存原始选中的文本
     Set originalSelection = Selection.Range.Duplicate

     inputText = Replace(Replace(Replace(Replace(Replace(Selection.text, "\",
"\\"), vbCrLf, ""), vbCr, ""), vbLf, ""), Chr(34), "\""")
     response = CallDeepSeekAPI(api_key, inputText)

     If Left(response, 5) <> "Error" Then
          Set regex = CreateObject("VBScript.RegExp")
          With regex
              .Global = True
              .MultiLine = True
              .IgnoreCase = False
              .Pattern = """content"":""(.*?)"""
          End With
          Set matches = regex.Execute(response)
          If matches.Count > 0 Then
              response = matches(0).SubMatches(0)
              ' 处理换行符和特殊字符
              response = Replace(response, "\n\n", vbNewLine)   ' 双换行替换为真实的单
换行
              response = Replace(response, "\n", vbNewLine)   ' 单换行替换为真实的换行
              response = Replace(Replace(response, """", Chr(34)), """", Chr(34))

              ' 取消选中原始文本
              Selection.Collapse Direction:=wdCollapseEnd

              ' 将内容插入到选中文字的下一行
              Selection.TypeParagraph ' 插入新行
              Selection.TypeText text:=response

              ' 将光标移回原来选中文本的末尾
              originalSelection.Select
          Else
              MsgBox "Failed to parse API response.", vbExclamation
          End If
     Else
          MsgBox response, vbCritical
     End If
End Sub
