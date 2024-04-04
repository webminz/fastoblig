# FastOBLIG

This tool provides a leightweight helping utility to interact with the _Learning Management System (LMS)_ Canvas, 
the open-source hosting platform GitHub and OpenAI's GPT chatbot in order to provide students more meaningful 
feedback on their code submissions for mandatory exercises. The motivation for this tool is simple:
The workday of an academic is often quite "packed" at the same time we are involved in many teaching activities
and want to provide useful formative feedback to our students, but often time is just barely enough for some 
superficial scanning of the student's work followed by a generic _"good job"_ feedback message. 
With the advent of generative AI and OpenAI's GPT in particular, the task of _code review_ might be possibly automated?

## How to use it?

First, you will have to install it with Poetry:

```bash
poetry install
```

afterwards, you may enter the Poetry-managed shell environment with 
```bash
poetry shell
```

in this shell, the `fastoblig` binary is available. Call:
```bash
fastoblig --help
```
to see your options.

You may first have to have a look at the `config` sub-command to set your _tokens_ (Canvas LMS, OpenAI API, and a GitHub access token with `issue:write` permission):
```bash
fastoblig config --help
```


Then, you can run the `fastoblig` binary. When you call it without parameters, it will tell you about the possible options.

You will also have to set the `CANVAS_TOKEN` environment variable, which has to contain the secret app token, which 
you have to create in Canvas and add as an integration.

## How to improve it?

This is work in progress, if you want too see more featres, feel free to create a pull request.
