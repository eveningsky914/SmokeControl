import streamlit as st

def metric(label, value, caption):
    st.metric(label, "데이터 없음" if value is None else f"{value:.1f}%")
    st.caption(caption)
